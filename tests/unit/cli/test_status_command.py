"""
Unit tests for the 'design-graph status' command.

Covers:
  - parse_status_args: flag parsing, defaults
  - GraphStatusReport: dataclass contract
  - render_status_report: formatting, all fields present
  - collect_graph_status: stale detection, missing state file
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from design_graph.cli.status import (
    GraphStatusReport,
    collect_graph_status,
    render_status_report,
)
from design_graph.cli.build import parse_status_args, StatusCliArgs


# ── parse_status_args ─────────────────────────────────────────────────────────

class TestParseStatusArgs:
    def test_no_args_returns_status_cli_args(self):
        args = parse_status_args([])
        assert isinstance(args, StatusCliArgs)

    def test_verbose_false_by_default(self):
        args = parse_status_args([])
        assert args.verbose is False

    def test_verbose_flag_enabled(self):
        args = parse_status_args(["--verbose"])
        assert args.verbose is True

    def test_db_flag_sets_custom_path(self, tmp_path):
        args = parse_status_args(["--db", str(tmp_path / "custom.db")])
        assert args.db_path == tmp_path / "custom.db"

    def test_db_path_none_by_default(self):
        args = parse_status_args([])
        assert args.db_path is None

    def test_returns_status_cli_args_dataclass(self):
        args = parse_status_args([])
        assert hasattr(args, "verbose")
        assert hasattr(args, "db_path")


# ── GraphStatusReport ─────────────────────────────────────────────────────────

class TestGraphStatusReport:
    def _make(self, **overrides) -> GraphStatusReport:
        defaults = dict(
            db_path=Path("/tmp/test.db"),
            db_size_bytes=102400,
            last_build="2026-06-06T10:15:23+00:00",
            html_hash="63f8bdbd",
            current_html_hash="63f8bdbd",
            kuzu_version="0.6.2",
            node_counts={"screens": 3, "components": 12, "tokens": 8,
                         "texts": 25, "styles": 40, "sections": 5,
                         "interactions": 4, "contains": 6},
        )
        return GraphStatusReport(**{**defaults, **overrides})

    def test_is_stale_false_when_hashes_match(self):
        r = self._make(html_hash="abc", current_html_hash="abc")
        assert r.is_stale is False

    def test_is_stale_true_when_hashes_differ(self):
        r = self._make(html_hash="abc", current_html_hash="xyz")
        assert r.is_stale is True

    def test_is_stale_true_when_last_build_empty(self):
        r = self._make(last_build="", html_hash="")
        assert r.is_stale is True

    def test_has_all_required_fields(self):
        r = self._make()
        assert hasattr(r, "db_path")
        assert hasattr(r, "db_size_bytes")
        assert hasattr(r, "last_build")
        assert hasattr(r, "html_hash")
        assert hasattr(r, "current_html_hash")
        assert hasattr(r, "kuzu_version")
        assert hasattr(r, "node_counts")
        assert hasattr(r, "is_stale")


# ── render_status_report ──────────────────────────────────────────────────────

class TestRenderStatusReport:
    def _fresh_report(self) -> GraphStatusReport:
        return GraphStatusReport(
            db_path=Path("/home/user/.local/share/design-graph/myapp.db"),
            db_size_bytes=204800,
            last_build="2026-06-06T10:15:23+00:00",
            html_hash="63f8bdbd",
            current_html_hash="63f8bdbd",
            kuzu_version="0.6.2",
            node_counts={"screens": 3, "components": 12, "tokens": 8,
                         "texts": 25, "styles": 40, "sections": 5,
                         "interactions": 4, "contains": 6},
        )

    def test_returns_string(self):
        assert isinstance(render_status_report(self._fresh_report()), str)

    def test_contains_db_path(self):
        output = render_status_report(self._fresh_report())
        assert "myapp.db" in output

    def test_contains_last_build_date(self):
        output = render_status_report(self._fresh_report())
        assert "2026" in output

    def test_contains_screens_count(self):
        output = render_status_report(self._fresh_report())
        assert "3" in output

    def test_contains_components_count(self):
        output = render_status_report(self._fresh_report())
        assert "12" in output

    def test_distinguishes_extracted_and_unresolved_components(self):
        report = self._fresh_report()
        report.node_counts.update({"extracted_components": 10, "unresolved_components": 2})

        output = render_status_report(report)

        assert "Extracted:" in output
        assert "Unresolved:" in output
        assert "10" in output

    def test_contains_kuzu_version(self):
        output = render_status_report(self._fresh_report())
        assert "0.6.2" in output

    def test_fresh_graph_shows_no_stale_indicator(self):
        output = render_status_report(self._fresh_report())
        assert "stale" not in output.lower()

    def test_stale_graph_shows_stale_indicator(self):
        stale = GraphStatusReport(
            db_path=Path("/tmp/old.db"),
            db_size_bytes=1024,
            last_build="2026-01-01T00:00:00+00:00",
            html_hash="oldHash",
            current_html_hash="newHash",
            kuzu_version="0.6.2",
            node_counts={"screens": 1, "components": 2, "tokens": 0,
                         "texts": 0, "styles": 0, "sections": 0,
                         "interactions": 0, "contains": 0},
        )
        output = render_status_report(stale)
        assert "stale" in output.lower() or "changed" in output.lower() or "⚠" in output

    def test_db_size_formatted_human_readable(self):
        output = render_status_report(self._fresh_report())
        assert "KB" in output or "MB" in output or "200" in output

    def test_never_build_shows_never_built_message(self):
        never_built = GraphStatusReport(
            db_path=Path("/tmp/empty.db"),
            db_size_bytes=0,
            last_build="",
            html_hash="",
            current_html_hash="",
            kuzu_version="0.6.2",
            node_counts={},
        )
        output = render_status_report(never_built)
        assert "never" in output.lower() or "no graph" in output.lower() or "build" in output.lower()


# ── collect_graph_status ──────────────────────────────────────────────────────

class TestCollectGraphStatus:
    def test_returns_report_for_existing_db(self, tmp_path):
        import asyncio
        from design_graph.pipeline.coordinator import run_pipeline
        from tests.unit.cli.test_status_command import _SIMPLE_HTML

        db_path    = tmp_path / "test.db"
        state_path = tmp_path / ".state.json"
        asyncio.run(run_pipeline(_SIMPLE_HTML, db_path, state_path))

        report = collect_graph_status(db_path=db_path, state_path=state_path)
        assert isinstance(report, GraphStatusReport)
        assert report.node_counts.get("screens", 0) >= 1

    def test_report_is_not_stale_when_hash_matches(self, tmp_path):
        import asyncio
        from design_graph.pipeline.coordinator import run_pipeline
        from tests.unit.cli.test_status_command import _SIMPLE_HTML

        db_path    = tmp_path / "test.db"
        state_path = tmp_path / ".state.json"
        asyncio.run(run_pipeline(_SIMPLE_HTML, db_path, state_path))

        report = collect_graph_status(db_path=db_path, state_path=state_path,
                                      html_path=_SIMPLE_HTML)
        assert report.is_stale is False

    def test_report_is_stale_when_state_file_missing(self, tmp_path):
        db_path    = tmp_path / "fake.db"
        state_path = tmp_path / ".no-state.json"
        report = collect_graph_status(db_path=db_path, state_path=state_path)
        assert report.is_stale is True

    def test_db_size_is_zero_for_nonexistent_db(self, tmp_path):
        report = collect_graph_status(
            db_path=tmp_path / "missing.db",
            state_path=tmp_path / "missing.json",
        )
        assert report.db_size_bytes == 0

    def test_kuzu_version_field_populated(self, tmp_path):
        report = collect_graph_status(
            db_path=tmp_path / "none.db",
            state_path=tmp_path / "none.json",
        )
        assert isinstance(report.kuzu_version, str)
        assert len(report.kuzu_version) > 0


# Module-level path for test reuse
_SIMPLE_HTML = Path(__file__).parent.parent.parent / "fixtures" / "simple.html"
