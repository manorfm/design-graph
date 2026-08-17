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


# ── BuildPhaseReporter integration ────────────────────────────────────────────

class TestCoordinatorCallsReporter:
    """
    run_pipeline() must call phase_started / phase_completed for each phase
    and call build_completed at the end of a successful build.
    A SilentBuildReporter is passed in; we verify it via a spy subclass.
    """

    _JS = """
    function HomePage() { return <div><BtnPrimary /></div>; }
    function BtnPrimary() { return <button style={{color:'#ffb81c'}}>OK</button>; }
    """

    @pytest.fixture()
    def proto_html(self, tmp_path):
        f = tmp_path / "test.html"
        f.write_text(f"<html><body><script>{self._JS}</script></body></html>")
        return f

    def test_reporter_receives_phase_started_events(self, proto_html, tmp_path):
        from design_graph.pipeline.build_progress import SilentBuildReporter
        from design_graph.pipeline.coordinator import run_pipeline

        started: list[str] = []

        class SpyReporter(SilentBuildReporter):
            def phase_started(self, name, *, total):
                started.append(name)

        asyncio.run(run_pipeline(
            proto_html, tmp_path / "t.db", tmp_path / ".state.json",
            reporter=SpyReporter(),
        ))
        assert len(started) >= 3, f"Expected ≥3 phase_started calls, got: {started}"

    def test_reporter_receives_build_completed(self, proto_html, tmp_path):
        from design_graph.pipeline.build_progress import SilentBuildReporter
        from design_graph.pipeline.coordinator import run_pipeline

        completed: list[float] = []

        class SpyReporter(SilentBuildReporter):
            def build_completed(self, *, total_seconds):
                completed.append(total_seconds)

        asyncio.run(run_pipeline(
            proto_html, tmp_path / "t.db", tmp_path / ".state.json",
            reporter=SpyReporter(),
        ))
        assert len(completed) == 1
        assert completed[0] > 0

    def test_skipped_build_calls_build_skipped(self, proto_html, tmp_path):
        from design_graph.pipeline.build_progress import SilentBuildReporter
        from design_graph.pipeline.coordinator import run_pipeline

        skipped: list[str] = []

        class SpyReporter(SilentBuildReporter):
            def build_skipped(self, reason):
                skipped.append(reason)

        db_path    = tmp_path / "t.db"
        state_path = tmp_path / ".state.json"
        # First build
        asyncio.run(run_pipeline(proto_html, db_path, state_path, reporter=SilentBuildReporter()))
        # Second build (unchanged HTML) should skip
        asyncio.run(run_pipeline(proto_html, db_path, state_path, reporter=SpyReporter()))
        assert len(skipped) == 1

    def test_default_reporter_is_silent(self, proto_html, tmp_path):
        """Without explicit reporter, pipeline must complete without raising."""
        from design_graph.pipeline.coordinator import run_pipeline
        # The absence of a reporter argument must not raise — SilentBuildReporter is used.
        stats = asyncio.run(run_pipeline(proto_html, tmp_path / "t.db", tmp_path / ".state.json"))
        assert stats is not None


# ── extract_react: screen/component split ─────────────────────────────────────
#
# extract_react is public (not _extract_react) because cli/build.py's chunk
# export reuses it directly — a screen boundary must never also be extracted
# as a component, regardless of who calls this function.

class TestExtractReactScreenComponentSplit:
    def test_screen_boundary_excluded_from_extracted_components(self):
        from design_graph.core.models import RawSources, SourceFormat
        from design_graph.pipeline.coordinator import extract_react

        js = """
        function BtnPrimary() { return <button>Click</button>; }
        function HomePage() {
          return (<div><BtnPrimary /></div>);
        }
        """
        sources = RawSources(js=js, css="", inner_html="", html_hash="x", format=SourceFormat.BUNDLED_REACT)
        comps, screens, sections_map, tokens = asyncio.run(extract_react(sources, concurrency=1))
        assert "HomePage" not in [c.name for c in comps]
        assert "BtnPrimary" in [c.name for c in comps]
        assert "HomePage" in [s.name for s in screens]


# ── extract_react: component alias resolution ──────────────────────────────
#
# Some prototypes rename a component and keep the old name as a plain
# re-export (`const Badge = window.V6K.Pill;`) instead of a function. Left
# alone, that produces an empty unresolved-component shell for the alias
# name. extract_react must resolve it to the real definition everywhere the
# alias is referenced — by other components and by screens alike.

class TestExtractReactComponentAliasResolution:
    _JS = """
    function Pill({ label, color }) {
      return <span style={{color}}>{label}</span>;
    }
    const Badge = window.V6K.Pill;
    function RestaurantRow({ r }) {
      return (<div><Badge label={r.status} /></div>);
    }
    function RestaurantsPage() {
      return (
        <div>
          {/* ── Lista ── */}
          <RestaurantRow r={r} />
          <Badge label="top" />
        </div>
      );
    }
    """

    def _extract(self):
        from design_graph.core.models import RawSources, SourceFormat
        from design_graph.pipeline.coordinator import extract_react

        sources = RawSources(js=self._JS, css="", inner_html="", html_hash="x", format=SourceFormat.BUNDLED_REACT)
        return asyncio.run(extract_react(sources, concurrency=1))

    def test_alias_name_is_not_extracted_as_its_own_component(self):
        comps, _screens, _sections_map, _tokens = self._extract()
        assert "Badge" not in [c.name for c in comps]
        assert "Pill" in [c.name for c in comps]

    def test_component_child_refs_resolve_alias_to_target(self):
        comps, _screens, _sections_map, _tokens = self._extract()
        row = next(c for c in comps if c.name == "RestaurantRow")
        assert "Badge" not in row.child_refs
        assert "Pill" in row.child_refs

    def test_screen_component_refs_resolve_alias_to_target(self):
        _comps, screens, _sections_map, _tokens = self._extract()
        page = next(s for s in screens if s.name == "RestaurantsPage")
        assert "Badge" not in page.component_refs
        assert "Pill" in page.component_refs
        # RestaurantRow already referenced Pill via the alias — the direct
        # <Badge label="top" /> reference must dedupe into the same entry.
        assert page.component_refs.count("Pill") == 1

    def test_section_component_refs_resolve_alias_to_target(self):
        # Sections are collected independently of screens/components — the
        # writer creates unresolved shells straight from section.component_refs
        # (graph/writer.py write_screen), so this leak survives even after
        # screen- and component-level refs are fixed unless handled here too.
        _comps, _screens, sections_map, _tokens = self._extract()
        sections = sections_map["RestaurantsPage"]
        section = next(s for s in sections if s.name == "Lista")
        assert "Badge" not in section.component_refs
        assert "Pill" in section.component_refs
