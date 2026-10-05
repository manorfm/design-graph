"""
Tests for scripts/release.py — the next version, decided at release time from
every commit since the last release, and the checks a release must pass.

Responsibilities under test:
  - parse_commit_prefix: extracts feat|fix|chore|refactor from a commit message
  - bump_for / next_version: the strongest bump among a release's commits
  - release_blockers: the states a release must refuse
  - parse_version: parses a "v1.2.3" or "1.2.3" tag string into (major, minor, patch)
  - format_version: formats (major, minor, patch) as "v1.2.3"
  - is_breaking_change: a Conventional Commits `type!:` subject marks a major bump
  - latest_version_tag: the highest released version among every tag, not the nearest one
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# scripts/ is not a package — add it to path for import
sys.path.insert(0, str(Path(__file__).parents[3] / "scripts"))
from release import (
    format_version,
    is_breaking_change,
    latest_version_tag,
    parse_commit_prefix,
    parse_version,
    bump_for,
    next_version,
    release_blockers,
)


# ── parse_version ─────────────────────────────────────────────────────────────

class TestParseVersion:
    def test_parses_v_prefixed_tag(self):
        assert parse_version("v1.2.3") == (1, 2, 3)

    def test_parses_bare_tag(self):
        assert parse_version("1.2.3") == (1, 2, 3)

    def test_parses_zero_version(self):
        assert parse_version("v0.0.0") == (0, 0, 0)

    def test_parses_large_numbers(self):
        assert parse_version("v12.34.56") == (12, 34, 56)

    def test_invalid_tag_raises(self):
        with pytest.raises(ValueError):
            parse_version("not-a-version")

    def test_incomplete_tag_raises(self):
        with pytest.raises(ValueError):
            parse_version("v1.2")


# ── format_version ────────────────────────────────────────────────────────────

class TestFormatVersion:
    def test_formats_with_v_prefix(self):
        assert format_version(1, 2, 3) == "v1.2.3"

    def test_formats_zero_version(self):
        assert format_version(0, 0, 0) == "v0.0.0"

    def test_roundtrip(self):
        tag = "v3.14.9"
        assert format_version(*parse_version(tag)) == tag


# ── parse_commit_prefix ───────────────────────────────────────────────────────

class TestParseCommitPrefix:
    @pytest.mark.parametrize("message,expected", [
        ("feat: added list_components MCP tool",     "feat"),
        ("fix: corrected CONTAINS depth in reader",  "fix"),
        ("chore: updated README and diagram",         "chore"),
        ("refactor: rewrote infer_component_type",   "refactor"),
        ("feat(scope): scoped commit",               "feat"),
        ("fix(parser): fix in parser",               "fix"),
    ])
    def test_known_prefixes_extracted(self, message, expected):
        assert parse_commit_prefix(message) == expected

    @pytest.mark.parametrize("message", [
        "update something without prefix",
        "Merge branch 'main'",
        "Initial commit",
        "",
        "  feat: leading space breaks it",
    ])
    def test_unknown_prefix_returns_none(self, message):
        assert parse_commit_prefix(message) is None

    def test_case_sensitive(self):
        assert parse_commit_prefix("Feat: capitalized") is None

    def test_requires_colon_separator(self):
        assert parse_commit_prefix("feat added something") is None


# ── One commit's bump ─────────────────────────────────────────────────────────

class TestSingleCommitBump:
    @pytest.mark.parametrize("current,subject,expected", [
        ("v0.0.0", "feat: x", "v0.1.0"),
        ("v0.1.4", "feat: x", "v0.2.0"),
        ("v1.2.3", "feat: x", "v1.3.0"),
        ("v0.0.0", "fix: x", "v0.0.1"),
        ("v1.2.3", "fix: x", "v1.2.4"),
        ("v1.2.3", "chore: x", "v1.2.4"),
        ("v1.2.3", "refactor: x", "v1.2.4"),
    ])
    def test_bump_rules(self, current, subject, expected):
        assert next_version([current], [subject]) == expected

    def test_feat_resets_patch_and_keeps_major(self):
        assert next_version(["v3.7.9"], ["feat: x"]) == "v3.8.0"


class TestBreakingChange:
    @pytest.mark.parametrize("message", [
        "feat!: replace the capture contract",
        "fix(model)!: rename source fields",
        "refactor!: move packages",
        "docs!: drop the legacy flag from the guide",
    ])
    def test_bang_before_the_colon_marks_a_breaking_change(self, message):
        assert is_breaking_change(message) is True

    @pytest.mark.parametrize("message", [
        "feat: add a capture", "fix: no bang", "feat! missing colon", "Feat!: wrong case", "chore: bump to v1!",
    ])
    def test_other_subjects_are_not_breaking(self, message):
        assert is_breaking_change(message) is False

    @pytest.mark.parametrize("current,expected", [("v0.34.0", "v1.0.0"), ("v1.4.2", "v2.0.0"), ("v0.0.0", "v1.0.0")])
    def test_breaking_change_bumps_major_and_resets_the_rest(self, current, expected):
        assert next_version([current], ["feat!: x"]) == expected

    def test_breaking_change_bumps_major_whatever_the_type(self):
        assert next_version(["v0.34.0"], ["docs!: drop a flag"]) == "v1.0.0"


# ── Current version ───────────────────────────────────────────────────────────

class TestLatestVersionTag:
    def test_highest_semver_wins_over_tag_order(self):
        assert latest_version_tag(["v0.33.0", "v0.34.0", "v0.9.0", "v0.33.1"]) == "v0.34.0"

    def test_numeric_not_lexical_comparison(self):
        assert latest_version_tag(["v0.9.0", "v0.10.0"]) == "v0.10.0"

    def test_non_version_tags_are_ignored(self):
        assert latest_version_tag(["release-candidate", "v1.2", "v1.0.0"]) == "v1.0.0"

    def test_no_version_tag_means_zero(self):
        assert latest_version_tag([]) == "0.0.0"


# ── Bump over a whole release ─────────────────────────────────────────────────

class TestBumpFor:
    def test_breaking_commit_anywhere_makes_a_major(self):
        assert bump_for(["fix: a", "feat!: b", "docs: c"]) == "major"

    def test_feature_beats_fixes(self):
        assert bump_for(["fix: a", "feat: b", "refactor: c"]) == "minor"

    def test_fixes_chores_and_refactors_make_a_patch(self):
        assert bump_for(["chore: a", "refactor: b"]) == "patch"

    def test_commits_that_change_nothing_shipped_make_no_release(self):
        assert bump_for(["docs: a", "test: b", "ci: c", "Merge branch x"]) is None

    def test_no_commits_make_no_release(self):
        assert bump_for([]) is None


class TestNextVersion:
    def test_applies_the_release_bump_to_the_highest_tag(self):
        assert next_version(["v0.34.0", "v1.0.0", "v0.9.0"], ["feat: x", "fix: y"]) == "v1.1.0"

    def test_major_resets_minor_and_patch(self):
        assert next_version(["v1.4.2"], ["refactor!: y"]) == "v2.0.0"

    def test_first_release_starts_from_zero(self):
        assert next_version([], ["fix: x"]) == "v0.0.1"

    def test_nothing_to_release_is_none(self):
        assert next_version(["v1.0.0"], ["docs: x"]) is None


# ── Release checks ────────────────────────────────────────────────────────────

class TestReleaseBlockers:
    _OK = {"branch": "main", "head": "abc", "remote_head": "abc", "clean": True, "next_tag": "v1.1.0",
           "tag_exists": False}

    def _blockers(self, **changes):
        return release_blockers(**{**self._OK, **changes})

    def test_a_clean_up_to_date_main_with_changes_can_release(self):
        assert self._blockers() == []

    @pytest.mark.parametrize("changes,reason", [
        ({"branch": "feat/x"}, "main"),
        ({"remote_head": "def"}, "origin/main"),
        ({"clean": False}, "uncommitted"),
        ({"next_tag": None}, "nothing to release"),
        ({"tag_exists": True}, "already exists"),
    ])
    def test_each_unsafe_state_blocks_with_its_reason(self, changes, reason):
        blockers = self._blockers(**changes)
        assert len(blockers) == 1 and reason in blockers[0]

