#!/usr/bin/env python3
"""
Commit-driven semantic versioner for design-graph.

Reads the latest git tag, parses the last commit message prefix, and creates
a new annotated tag following semver bump rules:

  type!:    → major bump  (0.34.0 → 1.0.0) — any type marked breaking with "!"
  feat:     → minor bump  (0.1.0 → 0.2.0, patch resets to 0)
  fix:      → patch bump  (0.1.0 → 0.1.1)
  chore:    → patch bump
  refactor: → patch bump

Unknown prefixes (docs, ci, test, …) produce no tag.

Usage (called by .githooks/post-commit):
  python scripts/auto_version.py

The current version is the highest vX.Y.Z tag in the repository, not the
nearest one reachable from HEAD — a release tagged on another line of history
must never make the next tag go backwards.

Pure functions (parse_version, format_version, parse_commit_prefix,
is_breaking_change, compute_next_version, latest_version_tag) are importable
for unit testing without git.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# ── Bump rules ────────────────────────────────────────────────────────────────

_MINOR_PREFIXES: frozenset[str] = frozenset({"feat"})
_PATCH_PREFIXES: frozenset[str] = frozenset({"fix", "chore", "refactor"})

# ── Pure functions (testable without git) ─────────────────────────────────────

_RE_VERSION = re.compile(r'^v?(\d+)\.(\d+)\.(\d+)$')
_RE_PREFIX  = re.compile(r'^(feat|fix|chore|refactor)(?:\([^)]*\))?!?:')
_RE_BREAKING = re.compile(r'^[a-z]+(?:\([^)]*\))?!:')


def parse_version(tag: str) -> tuple[int, int, int]:
    """Parse a 'v1.2.3' or '1.2.3' tag string into (major, minor, patch).

    Raises ValueError for unrecognised formats.
    """
    m = _RE_VERSION.match(tag.strip())
    if not m:
        raise ValueError(f"Cannot parse version tag: {tag!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def format_version(major: int, minor: int, patch: int) -> str:
    """Format a (major, minor, patch) triple as 'vMAJOR.MINOR.PATCH'."""
    return f"v{major}.{minor}.{patch}"


def parse_commit_prefix(message: str) -> str | None:
    """Extract the conventional-commit prefix from a commit message subject.

    Returns the prefix string ('feat', 'fix', 'chore', 'refactor') or None
    when the message does not match the conventional-commit format.
    """
    m = _RE_PREFIX.match(message)
    return m.group(1) if m else None


def is_breaking_change(message: str) -> bool:
    """True for a Conventional Commits breaking subject: `type!:` or `type(scope)!:`."""
    return bool(_RE_BREAKING.match(message))


def latest_version_tag(tags: list[str]) -> str:
    """The highest vX.Y.Z among `tags`, compared numerically; '0.0.0' when there is none."""
    versions = []
    for tag in tags:
        try:
            versions.append((parse_version(tag), tag))
        except ValueError:
            continue
    return max(versions)[1] if versions else "0.0.0"


def compute_next_version(current: str, prefix: str | None, breaking: bool = False) -> str:
    """Apply semver bump rules and return the new version string (no 'v' prefix).

    A breaking change bumps major whatever its type. Otherwise returns the
    current version unchanged when the prefix is unknown or None.
    """
    major, minor, patch = parse_version(current)

    if breaking:
        return f"{major + 1}.0.0"

    if prefix in _MINOR_PREFIXES:
        return f"{major}.{minor + 1}.0"
    if prefix in _PATCH_PREFIXES:
        return f"{major}.{minor}.{patch + 1}"
    return f"{major}.{minor}.{patch}"


# ── README badge updater ──────────────────────────────────────────────────────

_RE_README_BADGE = re.compile(
    r'(!\[Version\]\(https://img\.shields\.io/badge/version-)(v\d+\.\d+\.\d+)(-\w+\.svg\))'
)


def update_readme_version(new_tag: str, readme_path: Path) -> bool:
    """Replace the version badge in readme_path with new_tag.

    Returns True when the badge was found and updated, False otherwise.
    The caller is responsible for committing the file.
    """
    if not readme_path.exists():
        return False
    text = readme_path.read_text(encoding="utf-8")
    new_text, count = _RE_README_BADGE.subn(rf"\g<1>{new_tag}\g<3>", text)
    if count == 0:
        return False
    readme_path.write_text(new_text, encoding="utf-8")
    return True


# ── Git integration ───────────────────────────────────────────────────────────

def _git(*args: str) -> str:
    """Run a git command and return stdout. Raises on non-zero exit."""
    result = subprocess.run(
        ["git", *args],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _current_version_tag() -> str:
    """Return the highest semver git tag, or '0.0.0' when none exists."""
    try:
        return latest_version_tag(_git("tag", "--list", "v*").split())
    except subprocess.CalledProcessError:
        return "0.0.0"


def _last_commit_subject() -> str:
    """Return the subject line of the most recent commit."""
    return _git("log", "-1", "--pretty=%s")


def _tag_exists(tag: str) -> bool:
    try:
        _git("rev-parse", tag)
        return True
    except subprocess.CalledProcessError:
        return False


def _create_annotated_tag(tag: str, message: str) -> None:
    _git("tag", "-a", tag, "-m", message)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    subject  = _last_commit_subject()
    prefix   = parse_commit_prefix(subject)
    breaking = is_breaking_change(subject)

    if not breaking and prefix not in (_MINOR_PREFIXES | _PATCH_PREFIXES):
        print(f"auto_version: no bump — prefix {prefix!r} not in bump rules", file=sys.stderr)
        return 0

    current_tag    = _current_version_tag()
    next_version   = compute_next_version(current_tag, prefix, breaking)
    next_tag       = format_version(*parse_version(next_version))

    if _tag_exists(next_tag):
        print(f"auto_version: tag {next_tag} already exists — skipping", file=sys.stderr)
        return 0

    _create_annotated_tag(next_tag, subject)
    print(f"auto_version: {current_tag} → {next_tag}  ({prefix}{'!' if breaking else ''})", file=sys.stderr)

    readme = Path("README.md")
    if update_readme_version(next_tag, readme):
        _git("add", str(readme))
        _git("commit", "-m", f"chore: bump version to {next_tag}")
        print(f"auto_version: README updated to {next_tag}", file=sys.stderr)

    return 0


def _dry_run() -> int:
    """Print what the next version would be without creating a tag."""
    subject = _last_commit_subject()
    prefix  = parse_commit_prefix(subject)
    current = _current_version_tag()
    next_v  = compute_next_version(current, prefix, is_breaking_change(subject))
    next_tag = format_version(*parse_version(next_v))
    print(f"current: {current}  prefix: {prefix!r}  next: {next_tag}")
    return 0


if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        sys.exit(_dry_run())
    sys.exit(main())
