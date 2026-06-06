"""
Tests for scripts/auto_version.py — commit-driven semantic versioner.

Responsibilities under test:
  - parse_commit_prefix: extracts feat|fix|chore|refactor from a commit message
  - compute_next_version: applies semver bump rules given a prefix
  - parse_version: parses a "v1.2.3" or "1.2.3" tag string into (major, minor, patch)
  - format_version: formats (major, minor, patch) as "v1.2.3"
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# scripts/ is not a package — add it to path for import
sys.path.insert(0, str(Path(__file__).parents[3] / "scripts"))
from auto_version import (
    compute_next_version,
    format_version,
    parse_commit_prefix,
    parse_version,
    update_readme_version,
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


# ── compute_next_version ──────────────────────────────────────────────────────

class TestComputeNextVersion:
    @pytest.mark.parametrize("current,prefix,expected", [
        # feat → minor bump, patch reset to 0
        ("0.0.0", "feat",     "0.1.0"),
        ("0.1.4", "feat",     "0.2.0"),
        ("1.2.3", "feat",     "1.3.0"),
        # fix → patch bump
        ("0.0.0", "fix",      "0.0.1"),
        ("0.1.4", "fix",      "0.1.5"),
        ("1.2.3", "fix",      "1.2.4"),
        # chore → patch bump
        ("0.1.0", "chore",    "0.1.1"),
        ("1.2.3", "chore",    "1.2.4"),
        # refactor → patch bump
        ("0.1.0", "refactor", "0.1.1"),
        ("1.2.3", "refactor", "1.2.4"),
    ])
    def test_bump_rules(self, current, prefix, expected):
        assert compute_next_version(current, prefix) == expected

    def test_unknown_prefix_returns_same_version(self):
        assert compute_next_version("1.2.3", "docs") == "1.2.3"

    def test_none_prefix_returns_same_version(self):
        assert compute_next_version("1.2.3", None) == "1.2.3"

    def test_feat_resets_patch(self):
        result = compute_next_version("0.1.9", "feat")
        assert result == "0.2.0"

    def test_preserves_major_on_minor_bump(self):
        result = compute_next_version("3.7.2", "feat")
        assert result.startswith("3.")

    def test_output_has_no_v_prefix(self):
        result = compute_next_version("0.0.0", "feat")
        assert not result.startswith("v")


# ── update_readme_version ─────────────────────────────────────────────────────

_BADGE_LINE = (
    "[![Version](https://img.shields.io/badge/version-{tag}-green.svg)]"
    "(https://github.com/manorfm/design-graph/tags)"
)


class TestUpdateReadmeVersion:
    def _make_readme(self, tmp_path, tag: str) -> "Path":
        from pathlib import Path
        readme = tmp_path / "README.md"
        readme.write_text(
            f"# design-graph\n\n{_BADGE_LINE.format(tag=tag)}\n\n## Section\n",
            encoding="utf-8",
        )
        return readme

    def test_replaces_version_tag_in_badge(self, tmp_path):
        readme = self._make_readme(tmp_path, "v0.0.0")
        changed = update_readme_version("v1.2.3", readme)
        assert changed is True
        text = readme.read_text(encoding="utf-8")
        assert "v1.2.3" in text
        assert "v0.0.0" not in text

    def test_returns_false_when_badge_absent(self, tmp_path):
        from pathlib import Path
        readme = tmp_path / "README.md"
        readme.write_text("# No badge here\n", encoding="utf-8")
        assert update_readme_version("v1.2.3", readme) is False

    def test_preserves_rest_of_file(self, tmp_path):
        readme = self._make_readme(tmp_path, "v0.1.0")
        update_readme_version("v0.2.0", readme)
        text = readme.read_text(encoding="utf-8")
        assert "# design-graph" in text
        assert "## Section" in text

    def test_updates_any_existing_version(self, tmp_path):
        readme = self._make_readme(tmp_path, "v3.14.9")
        update_readme_version("v4.0.0", readme)
        assert "v4.0.0" in readme.read_text(encoding="utf-8")

    def test_returns_false_when_file_does_not_exist(self, tmp_path):
        from pathlib import Path
        missing = tmp_path / "NONEXISTENT.md"
        assert update_readme_version("v1.0.0", missing) is False

    def test_badge_url_color_is_preserved(self, tmp_path):
        readme = self._make_readme(tmp_path, "v0.0.0")
        update_readme_version("v1.0.0", readme)
        text = readme.read_text(encoding="utf-8")
        assert "-green.svg" in text

    def test_idempotent_on_same_version(self, tmp_path):
        readme = self._make_readme(tmp_path, "v1.0.0")
        update_readme_version("v1.0.0", readme)
        assert readme.read_text(encoding="utf-8").count("v1.0.0") == 1
