"""
End-to-end tests for 'design-graph status' command.

Builds a real graph and exercises the full status command flow including:
  - main() routing to _run_status
  - _auto_detect_db (with and without databases present)
  - collect_graph_status with a real db (stale detection, size)
  - render_status_report (output formatting with real data)
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from unittest.mock import patch

import pytest

from design_graph.pipeline.coordinator import run_pipeline

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"
SIMPLE_HTML = FIXTURE_DIR / "simple.html"


@pytest.fixture(scope="module")
def built_graph(tmp_path_factory):
    tmp        = tmp_path_factory.mktemp("status_e2e")
    db_path    = tmp / "simple.db"
    state_path = tmp / ".graph-state.json"
    asyncio.run(run_pipeline(SIMPLE_HTML, db_path, state_path))
    return tmp, db_path, state_path


# ── status command via main() ─────────────────────────────────────────────────

class TestStatusCommandEndToEnd:
    def test_status_command_routed_from_main(self, built_graph, capsys, monkeypatch):
        tmp, db_path, _ = built_graph
        monkeypatch.setenv("GRAPH_DIR", str(tmp))
        with patch("sys.argv", ["design-graph", "status", "--db", str(db_path)]):
            from design_graph.cli.build import main
            main()
        out = capsys.readouterr().out
        assert isinstance(out, str) and len(out) > 0

    def test_status_output_contains_db_name(self, built_graph, capsys, monkeypatch):
        tmp, db_path, _ = built_graph
        monkeypatch.setenv("GRAPH_DIR", str(tmp))
        with patch("sys.argv", ["design-graph", "status", "--db", str(db_path)]):
            from design_graph.cli.build import main
            main()
        out = capsys.readouterr().out
        assert "simple" in out.lower() or "db" in out.lower()

    def test_status_output_contains_screens(self, built_graph, capsys, monkeypatch):
        tmp, db_path, _ = built_graph
        monkeypatch.setenv("GRAPH_DIR", str(tmp))
        with patch("sys.argv", ["design-graph", "status", "--db", str(db_path)]):
            from design_graph.cli.build import main
            main()
        out = capsys.readouterr().out
        assert "Screen" in out or "screen" in out.lower() or "1" in out

    def test_status_with_no_graphs_shows_build_guidance(self, tmp_path, capsys, monkeypatch):
        empty = tmp_path / "empty_graphs"
        empty.mkdir()
        monkeypatch.setenv("GRAPH_DIR", str(empty))
        with patch("sys.argv", ["design-graph", "status"]):
            from design_graph.cli.build import main
            main()
        out = capsys.readouterr().out
        assert "never" in out.lower() or "build" in out.lower() or "no graph" in out.lower()

    def test_status_verbose_flag_accepted(self, built_graph, capsys, monkeypatch):
        tmp, db_path, _ = built_graph
        monkeypatch.setenv("GRAPH_DIR", str(tmp))
        with patch("sys.argv", ["design-graph", "status", "--db", str(db_path), "--verbose"]):
            from design_graph.cli.build import main
            main()
        out = capsys.readouterr().out
        assert isinstance(out, str)


# ── _auto_detect_db ───────────────────────────────────────────────────────────

class TestAutoDetectDb:
    def test_finds_db_in_graph_dir(self, built_graph, monkeypatch):
        tmp, db_path, _ = built_graph
        monkeypatch.setenv("GRAPH_DIR", str(tmp))
        from design_graph.cli.build import _auto_detect_db
        result = _auto_detect_db()
        assert result.suffix == ".db"

    def test_returns_default_when_no_dbs(self, tmp_path, monkeypatch):
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setenv("GRAPH_DIR", str(empty))
        from design_graph.cli.build import _auto_detect_db
        result = _auto_detect_db()
        assert result.suffix == ".db"

    def test_returns_default_when_dir_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GRAPH_DIR", str(tmp_path / "nonexistent"))
        from design_graph.cli.build import _auto_detect_db
        result = _auto_detect_db()
        assert result.suffix == ".db"

    def test_refuses_to_choose_silently_when_multiple_databases_exist(self, tmp_path, monkeypatch):
        (tmp_path / "one.db").mkdir()
        (tmp_path / "two.db").mkdir()
        monkeypatch.setenv("GRAPH_DIR", str(tmp_path))
        from design_graph.cli.build import _auto_detect_db
        with pytest.raises(SystemExit):
            _auto_detect_db()


# ── collect_graph_status with real data ──────────────────────────────────────

class TestCollectGraphStatusRealData:
    def test_db_size_positive_for_built_graph(self, built_graph):
        from design_graph.cli.status import collect_graph_status
        _, db_path, state_path = built_graph
        report = collect_graph_status(db_path=db_path, state_path=state_path)
        assert report.db_size_bytes > 0

    def test_screens_count_positive(self, built_graph):
        from design_graph.cli.status import collect_graph_status
        _, db_path, state_path = built_graph
        report = collect_graph_status(db_path=db_path, state_path=state_path)
        assert report.node_counts.get("screens", 0) >= 1

    def test_health_metrics_include_token_distribution_and_connectivity(self, built_graph):
        from design_graph.cli.status import collect_graph_status
        _, db_path, state_path = built_graph
        report = collect_graph_status(db_path=db_path, state_path=state_path)
        assert sum(report.health.token_categories.values()) == report.node_counts["tokens"]
        assert report.health.screens_with_components <= report.node_counts["screens"]
        assert report.health.components_with_screens <= report.node_counts["components"]

    def test_stale_detection_with_html_path(self, built_graph):
        from design_graph.cli.status import collect_graph_status
        _, db_path, state_path = built_graph
        report = collect_graph_status(
            db_path=db_path, state_path=state_path, html_path=SIMPLE_HTML
        )
        assert report.is_stale is False

    def test_stale_detection_when_html_changes(self, built_graph, tmp_path):
        from design_graph.cli.status import collect_graph_status
        _, db_path, state_path = built_graph
        # Create a "modified" HTML
        modified_html = tmp_path / "modified.html"
        modified_html.write_text("<html><body><p>Changed content</p></body></html>")
        report = collect_graph_status(
            db_path=db_path, state_path=state_path, html_path=modified_html
        )
        assert report.is_stale is True


# ── render_status_report with real data ──────────────────────────────────────

class TestRenderStatusReportRealData:
    def test_render_with_real_graph(self, built_graph):
        from design_graph.cli.status import collect_graph_status, render_status_report
        _, db_path, state_path = built_graph
        report = collect_graph_status(db_path=db_path, state_path=state_path)
        output = render_status_report(report)
        assert "Screen" in output or "screen" in output.lower()

    def test_db_size_formatted(self, built_graph):
        from design_graph.cli.status import collect_graph_status, render_status_report
        _, db_path, state_path = built_graph
        report = collect_graph_status(db_path=db_path, state_path=state_path)
        output = render_status_report(report)
        assert "KB" in output or "MB" in output or "B" in output
