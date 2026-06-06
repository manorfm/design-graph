#!/usr/bin/env python3
"""
Commit-driven semantic versioner for design-graph.

Reads the latest git tag, parses the last commit message prefix, and creates
a new annotated tag following semver bump rules:

  feat:     → minor bump  (0.1.0 → 0.2.0, patch resets to 0)
  fix:      → patch bump  (0.1.0 → 0.1.1)
  chore:    → patch bump
  refactor: → patch bump

Unknown prefixes (docs, ci, test, …) produce no tag.

Usage (called by .githooks/post-commit):
  python scripts/auto_version.py

Pure functions (parse_version, format_version, parse_commit_prefix,
compute_next_version) are importable for unit testing without git.
"""

from __future__ import annotations

import re
import subprocess
import sys

# ── Bump rules ────────────────────────────────────────────────────────────────

_MINOR_PREFIXES: frozenset[str] = frozenset({"feat"})
_PATCH_PREFIXES: frozenset[str] = frozenset({"fix", "chore", "refactor"})

# ── Pure functions (testable without git) ─────────────────────────────────────

_RE_VERSION = re.compile(r'^v?(\d+)\.(\d+)\.(\d+)$')
_RE_PREFIX  = re.compile(r'^(feat|fix|chore|refactor)(?:\([^)]*\))?:')


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


def compute_next_version(current: str, prefix: str | None) -> str:
    """Apply semver bump rules and return the new version string (no 'v' prefix).

    Returns the current version unchanged when the prefix is unknown or None.
    """
    major, minor, patch = parse_version(current)

    if prefix in _MINOR_PREFIXES:
        return f"{major}.{minor + 1}.0"
    if prefix in _PATCH_PREFIXES:
        return f"{major}.{minor}.{patch + 1}"
    return f"{major}.{minor}.{patch}"


# ── Git integration ───────────────────────────────────────────────────────────

def _git(*args: str) -> str:
    """Run a git command and return stdout. Raises on non-zero exit."""
    result = subprocess.run(
        ["git", *args],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _current_version_tag() -> str:
    """Return the latest semver git tag, or '0.0.0' when none exists."""
    try:
        tag = _git("describe", "--tags", "--abbrev=0", "--match", "v*")
        parse_version(tag)   # validate it looks like a version
        return tag
    except (subprocess.CalledProcessError, ValueError):
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
    subject = _last_commit_subject()
    prefix  = parse_commit_prefix(subject)

    if prefix not in (_MINOR_PREFIXES | _PATCH_PREFIXES):
        print(f"auto_version: no bump — prefix {prefix!r} not in bump rules", file=sys.stderr)
        return 0

    current_tag    = _current_version_tag()
    next_version   = compute_next_version(current_tag, prefix)
    next_tag       = format_version(*parse_version(next_version))

    if _tag_exists(next_tag):
        print(f"auto_version: tag {next_tag} already exists — skipping", file=sys.stderr)
        return 0

    _create_annotated_tag(next_tag, subject)
    print(f"auto_version: {current_tag} → {next_tag}  ({prefix})", file=sys.stderr)
    return 0


def _dry_run() -> int:
    """Print what the next version would be without creating a tag."""
    subject = _last_commit_subject()
    prefix  = parse_commit_prefix(subject)
    current = _current_version_tag()
    next_v  = compute_next_version(current, prefix)
    next_tag = format_version(*parse_version(next_v))
    print(f"current: {current}  prefix: {prefix!r}  next: {next_tag}")
    return 0


if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        sys.exit(_dry_run())
    sys.exit(main())
