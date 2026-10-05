#!/usr/bin/env python3
"""
Release versioning for design-graph.

A version exists only when a release is made: on an up-to-date `main`, the
next version is the highest vX.Y.Z tag bumped by the strongest change among
**every** commit since the last release —

  type!:   → major  (any type marked breaking with "!")
  feat:    → minor
  fix:, chore:, refactor: → patch
  anything else (docs, test, ci…) ships nothing on its own

The base is the highest tag in the repository, not the nearest reachable
one: a release tagged on another line of history must never make the next
version go backwards.

usage:
  python scripts/release.py --next     print the next version (empty when nothing to release)
  python scripts/release.py --publish  check, tag main, push the tag and create the GitHub release
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys

_MAJOR, _MINOR, _PATCH = "major", "minor", "patch"
_BUMP_ORDER = (_MAJOR, _MINOR, _PATCH)
_MINOR_PREFIXES: frozenset[str] = frozenset({"feat"})
_PATCH_PREFIXES: frozenset[str] = frozenset({"fix", "chore", "refactor"})
RELEASE_BRANCH = "main"

_RE_VERSION = re.compile(r'^v?(\d+)\.(\d+)\.(\d+)$')
_RE_PREFIX = re.compile(r'^(feat|fix|chore|refactor)(?:\([^)]*\))?!?:')
_RE_BREAKING = re.compile(r'^[a-z]+(?:\([^)]*\))?!:')


# ── Versions ──────────────────────────────────────────────────────────────────

def parse_version(tag: str) -> tuple[int, int, int]:
    """Parse a 'v1.2.3' or '1.2.3' tag into (major, minor, patch); ValueError otherwise."""
    m = _RE_VERSION.match(tag.strip())
    if not m:
        raise ValueError(f"Cannot parse version tag: {tag!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def format_version(major: int, minor: int, patch: int) -> str:
    return f"v{major}.{minor}.{patch}"


def latest_version_tag(tags: list[str]) -> str:
    """The highest vX.Y.Z among `tags`, compared numerically; '0.0.0' when there is none."""
    versions = []
    for tag in tags:
        try:
            versions.append((parse_version(tag), tag))
        except ValueError:
            continue
    return max(versions)[1] if versions else "0.0.0"


# ── Commits → bump ────────────────────────────────────────────────────────────

def parse_commit_prefix(message: str) -> str | None:
    """The conventional-commit type that can ship (feat/fix/chore/refactor), or None."""
    m = _RE_PREFIX.match(message)
    return m.group(1) if m else None


def is_breaking_change(message: str) -> bool:
    """True for a Conventional Commits breaking subject: `type!:` or `type(scope)!:`."""
    return bool(_RE_BREAKING.match(message))


def _bump_of(subject: str) -> str | None:
    if is_breaking_change(subject):
        return _MAJOR
    prefix = parse_commit_prefix(subject)
    if prefix in _MINOR_PREFIXES:
        return _MINOR
    return _PATCH if prefix in _PATCH_PREFIXES else None


def bump_for(subjects: list[str]) -> str | None:
    """The strongest bump among a release's commit subjects; None when none ships."""
    bumps = {_bump_of(subject) for subject in subjects}
    return next((bump for bump in _BUMP_ORDER if bump in bumps), None)


def next_version(tags: list[str], subjects: list[str]) -> str | None:
    """The tag the next release gets, or None when its commits ship nothing."""
    bump = bump_for(subjects)
    if bump is None:
        return None
    major, minor, patch = parse_version(latest_version_tag(tags))
    if bump == _MAJOR:
        return format_version(major + 1, 0, 0)
    if bump == _MINOR:
        return format_version(major, minor + 1, 0)
    return format_version(major, minor, patch + 1)


# ── Release checks ────────────────────────────────────────────────────────────

def release_blockers(
    *, branch: str, head: str, remote_head: str, clean: bool, next_tag: str | None, tag_exists: bool,
) -> list[str]:
    """Every reason the current checkout must not be released; empty when it can."""
    blockers = []
    if branch != RELEASE_BRANCH:
        blockers.append(f"releases are made from {RELEASE_BRANCH}, not {branch!r}")
    elif head != remote_head:
        blockers.append(f"local {RELEASE_BRANCH} differs from origin/{RELEASE_BRANCH} — pull or push first")
    if not clean:
        blockers.append("the working tree has uncommitted changes")
    if next_tag is None:
        blockers.append("nothing to release — no feat/fix/chore/refactor commit since the last release")
    elif tag_exists:
        blockers.append(f"tag {next_tag} already exists")
    return blockers


# ── Git ───────────────────────────────────────────────────────────────────────

def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()


def _subjects_since_last_release() -> list[str]:
    """Commit subjects since the most recent release reachable from HEAD (all, before the first)."""
    try:
        last = _git("describe", "--tags", "--abbrev=0", "--match", "v*")
        log_range = f"{last}..HEAD"
    except subprocess.CalledProcessError:
        log_range = "HEAD"
    return [line for line in _git("log", "--format=%s", log_range).splitlines() if line]


def _next_tag() -> str | None:
    return next_version(_git("tag", "--list", "v*").split(), _subjects_since_last_release())


def _publish() -> int:
    if shutil.which("gh") is None:
        print("release: GitHub CLI 'gh' not found — https://cli.github.com", file=sys.stderr)
        return 1
    _git("fetch", "--quiet", "origin", RELEASE_BRANCH, "--tags")
    tag = _next_tag()
    blockers = release_blockers(
        branch=_git("rev-parse", "--abbrev-ref", "HEAD"),
        head=_git("rev-parse", "HEAD"),
        remote_head=_git("rev-parse", f"origin/{RELEASE_BRANCH}"),
        clean=_git("status", "--porcelain") == "",
        next_tag=tag,
        tag_exists=bool(tag) and bool(_git("tag", "--list", tag)),
    )
    if blockers:
        print("release: refused —\n  " + "\n  ".join(blockers), file=sys.stderr)
        return 1
    _git("tag", "-a", tag, "-m", f"Release {tag}")
    _git("push", "origin", tag)
    subprocess.run(["gh", "release", "create", tag, "--title", tag, "--generate-notes"], check=True)
    print(f"release: published {tag} — the publish workflow now awaits approval")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Release versioning for design-graph.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--next", action="store_true", help="Print the next version")
    action.add_argument("--publish", action="store_true", help="Tag main and publish the GitHub release")
    args = parser.parse_args(argv)
    if args.next:
        print(_next_tag() or "")
        return 0
    return _publish()


if __name__ == "__main__":
    sys.exit(main())
