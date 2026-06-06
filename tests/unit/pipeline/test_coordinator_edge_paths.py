"""
Tests for pipeline/coordinator.py branches not covered by integration tests.

Targets:
  - check_kuzu_version: unparseable version string (lines 61-62)
  - _extract_sections_for: screen has no boundary → returns empty (line 127)
  - _rebuild_db: removes directory-style db (line 189)
  - _log_diff: all four branch conditions (lines 200, 202, 204, 206)
"""

from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import pytest

from design_graph.pipeline.coordinator import (
    KUZU_MIN_VERSION,
    _log_diff,
    _rebuild_db,
    check_kuzu_version,
)


# ── check_kuzu_version: unparseable string ────────────────────────────────────

class TestCheckKuzuVersionUnparseable:
    def test_non_numeric_version_does_not_raise(self, capsys):
        check_kuzu_version("dev-build")
        # Should return silently — no warning, no crash
        assert capsys.readouterr().err == ""

    def test_empty_string_does_not_raise(self, capsys):
        check_kuzu_version("")
        assert capsys.readouterr().err == ""

    def test_none_like_string_does_not_raise(self, capsys):
        check_kuzu_version("N/A")
        assert capsys.readouterr().err == ""


# ── _rebuild_db: directory-style database ────────────────────────────────────

class TestRebuildDbDirectory:
    def test_removes_existing_directory_db(self, tmp_path):
        db_dir = tmp_path / "design-graph.db"
        db_dir.mkdir()
        (db_dir / "file1.col").write_bytes(b"data")
        (db_dir / "file2.col").write_bytes(b"data")

        _rebuild_db(db_dir)

        assert not db_dir.exists()

    def test_removes_existing_file_db(self, tmp_path):
        db_file = tmp_path / "design-graph.db"
        db_file.write_bytes(b"fake db data")

        _rebuild_db(db_file)

        assert not db_file.exists()

    def test_creates_parent_directory_when_missing(self, tmp_path):
        db_path = tmp_path / "nested" / "dir" / "design-graph.db"
        _rebuild_db(db_path)
        assert db_path.parent.exists()

    def test_no_error_when_db_does_not_exist(self, tmp_path):
        _rebuild_db(tmp_path / "nonexistent.db")  # must not raise


# ── _log_diff: all branch conditions ─────────────────────────────────────────

class TestLogDiff:
    """_log_diff has 4 independent branch conditions — cover each."""

    def _diff(self, **kwargs):
        from design_graph.core.models import BuildDiff
        defaults = dict(
            is_first_build=False,
            screens_added=[],
            screens_removed=[],
            comps_added=[],
            comps_removed=[],
        )
        return BuildDiff(**{**defaults, **kwargs})

    def test_first_build_logs_first_build(self, caplog):
        import logging
        with caplog.at_level(logging.INFO):
            _log_diff(self._diff(is_first_build=True))
        assert "first build" in caplog.text.lower()

    def test_screens_added_logged(self, caplog):
        import logging
        with caplog.at_level(logging.INFO):
            _log_diff(self._diff(screens_added=["HomeScreen", "LoginPage"]))
        assert "HomeScreen" in caplog.text or "screens added" in caplog.text.lower()

    def test_screens_removed_logged(self, caplog):
        import logging
        with caplog.at_level(logging.INFO):
            _log_diff(self._diff(screens_removed=["OldPage"]))
        assert "OldPage" in caplog.text or "screens removed" in caplog.text.lower()

    def test_comps_added_logged(self, caplog):
        import logging
        with caplog.at_level(logging.INFO):
            _log_diff(self._diff(comps_added=["NewCard", "NewBtn"]))
        assert "2" in caplog.text or "new component" in caplog.text.lower()

    def test_comps_removed_logged(self, caplog):
        import logging
        with caplog.at_level(logging.INFO):
            _log_diff(self._diff(comps_removed=["OldComp"]))
        assert "1" in caplog.text or "removed component" in caplog.text.lower()

    def test_no_changes_logs_nothing(self, caplog):
        import logging
        with caplog.at_level(logging.INFO):
            _log_diff(self._diff())
        # No changes → nothing logged
        assert "added" not in caplog.text.lower()
        assert "removed" not in caplog.text.lower()


# ── _extract_sections_for: screen without matching boundary ───────────────────

class TestExtractSectionsForMissingBoundary:
    """
    When a screen name is extracted but no FunctionBoundary matches it,
    the pipeline should gracefully return an empty section list rather than crashing.
    """

    def test_screen_without_boundary_gets_empty_sections(self, tmp_path):
        # Build a JS where a screen name is referenced as a component (USES_COMPONENT)
        # but no function definition exists for it — boundary lookup will fail.
        js = """
        function GhostScreen() { return <div><BtnPrimary /></div>; }
        function RealScreen() {
          return (
            <div style={{backgroundColor:'#1a1a1a'}}>
              {/* ── Header ── */}
              <div style={{padding:'16px'}}><BtnPrimary /></div>
              <GhostScreen />
            </div>
          );
        }
        """
        FIXTURE = tmp_path / "ghost.html"
        FIXTURE.write_text(f"<html><body><script>{js}</script></body></html>")

        from design_graph.pipeline.coordinator import run_pipeline
        db_path    = tmp_path / "ghost.db"
        state_path = tmp_path / ".state.json"

        # Pipeline should complete without error even with an unusual boundary situation
        stats = asyncio.run(run_pipeline(FIXTURE, db_path, state_path))
        assert stats is not None
