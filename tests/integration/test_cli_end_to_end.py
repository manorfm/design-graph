"""
End-to-end CLI tests.

These tests invoke the CLI entry-point functions (main()) with controlled
sys.argv, capture stdout/stderr, and verify exit codes. They use a real
HTML fixture and build a real Kuzu graph exactly once per module via a
module-scoped fixture.

Coverage:
  design-graph build — builds, skips, forces, --diff, --quiet, --verbose
  design-graph chunk — exports JSONL, respects --max-chars and --output
  design-query       — every subcommand against a real graph
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import kuzu
import pytest

from design_graph.pipeline.coordinator import run_pipeline

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"
SIMPLE_HTML = FIXTURE_DIR / "simple.html"


# ── shared graph for query tests ──────────────────────────────────────────────

@pytest.fixture(scope="module")
def built_graph_dir(tmp_path_factory):
    """Build a real graph once and return (graph_dir, db_path, html_path)."""
    tmp       = tmp_path_factory.mktemp("cli_e2e")
    db_path   = tmp / "simple.db"
    state     = tmp / ".graph-state.json"
    asyncio.run(run_pipeline(SIMPLE_HTML, db_path, state))
    return tmp, db_path


# ── design-graph build ────────────────────────────────────────────────────────

class TestBuildCommand:
    def test_build_creates_db_file(self, tmp_path):
        db_path = tmp_path / "out.db"
        with patch("sys.argv", ["design-graph", str(SIMPLE_HTML), "--db", str(db_path)]):
            from design_graph.cli.build import main
            main()
        assert db_path.exists()

    def test_build_accepts_named_database(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GRAPH_DIR", str(tmp_path))
        with patch("sys.argv", ["design-graph", str(SIMPLE_HTML), "--name", "My App"]):
            from design_graph.cli.build import main
            main()
        assert (tmp_path / "My App.db").exists()

    def test_named_build_recovers_from_orphan_state(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("GRAPH_DIR", str(tmp_path))
        argv = ["design-graph", str(SIMPLE_HTML), "--name", "My App"]
        with patch("sys.argv", argv):
            from design_graph.cli.build import main
            main()
        (tmp_path / "My App.db").unlink()
        capsys.readouterr()

        with patch("sys.argv", argv):
            main()

        assert (tmp_path / "My App.db").exists()
        assert "skipped" not in capsys.readouterr().out.lower()

    def test_build_prints_summary_to_stdout(self, tmp_path, capsys):
        db_path = tmp_path / "out.db"
        with patch("sys.argv", ["design-graph", str(SIMPLE_HTML), "--db", str(db_path)]):
            from design_graph.cli.build import main
            main()
        out = capsys.readouterr().out
        assert "Screens" in out or "screens" in out.lower()
        assert "Components" in out or "components" in out.lower()

    def test_quiet_flag_suppresses_summary(self, tmp_path, capsys):
        db_path = tmp_path / "out.db"
        with patch("sys.argv", ["design-graph", str(SIMPLE_HTML),
                                "--db", str(db_path), "--quiet"]):
            from design_graph.cli.build import main
            main()
        out = capsys.readouterr().out
        assert out.strip() == ""

    def test_skip_unchanged_prints_skip_message(self, tmp_path, capsys):
        db_path    = tmp_path / "out.db"
        state_path = tmp_path / ".graph-state.json"
        # First build
        asyncio.run(run_pipeline(SIMPLE_HTML, db_path, state_path))
        # Second build — should skip
        with patch("sys.argv", ["design-graph", str(SIMPLE_HTML), "--db", str(db_path)]):
            from design_graph.cli.build import main
            main()
        out = capsys.readouterr().out
        assert "unchanged" in out.lower() or "skipped" in out.lower()

    def test_force_flag_rebuilds_unchanged(self, tmp_path, capsys):
        db_path = tmp_path / "out.db"
        # First build
        with patch("sys.argv", ["design-graph", str(SIMPLE_HTML), "--db", str(db_path)]):
            from design_graph.cli.build import main
            main()
        capsys.readouterr()  # clear
        # Force rebuild
        with patch("sys.argv", ["design-graph", str(SIMPLE_HTML),
                                "--db", str(db_path), "--force"]):
            main()
        out = capsys.readouterr().out
        # Should print a summary (not a skip message)
        assert "unchanged" not in out.lower()

    def test_missing_file_exits_with_error(self, tmp_path, capsys):
        ghost = tmp_path / "ghost.html"
        with patch("sys.argv", ["design-graph", str(ghost)]):
            from design_graph.cli.build import main
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code != 0
        err = capsys.readouterr().err
        assert "not found" in err.lower() or "ghost" in err.lower()

    def test_help_flag_exits_zero(self):
        with patch("sys.argv", ["design-graph", "--help"]):
            from design_graph.cli.build import main
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 0

    def test_diff_flag_does_not_crash(self, tmp_path, capsys):
        db_path = tmp_path / "out.db"
        with patch("sys.argv", ["design-graph", str(SIMPLE_HTML),
                                "--db", str(db_path), "--diff"]):
            from design_graph.cli.build import main
            main()
        # Should complete without exception


# ── design-graph chunk ────────────────────────────────────────────────────────

class TestChunkCommand:
    def test_chunk_creates_jsonl_file(self, tmp_path):
        out = tmp_path / "chunks.jsonl"
        with patch("sys.argv", ["design-graph", "chunk", str(SIMPLE_HTML),
                                "--output", str(out)]):
            from design_graph.cli.build import main
            main()
        assert out.exists()

    def test_chunk_default_output_next_to_input(self, tmp_path):
        import shutil
        # Copy fixture so the .jsonl ends up in tmp_path
        local_html = tmp_path / "proto.html"
        shutil.copy(SIMPLE_HTML, local_html)
        expected_jsonl = local_html.with_suffix(".jsonl")
        with patch("sys.argv", ["design-graph", "chunk", str(local_html)]):
            from design_graph.cli.build import main
            main()
        assert expected_jsonl.exists()

    def test_chunk_output_contains_valid_json_lines(self, tmp_path):
        import json
        out = tmp_path / "chunks.jsonl"
        with patch("sys.argv", ["design-graph", "chunk", str(SIMPLE_HTML),
                                "--output", str(out)]):
            from design_graph.cli.build import main
            main()
        lines = out.read_text().splitlines()
        assert len(lines) >= 1
        for line in lines:
            data = json.loads(line)
            assert "chunk_id" in data
            assert "content" in data

    def test_chunk_respects_max_chars(self, tmp_path):
        import json
        out = tmp_path / "chunks.jsonl"
        max_c = 500
        with patch("sys.argv", ["design-graph", "chunk", str(SIMPLE_HTML),
                                "--output", str(out), "--max-chars", str(max_c)]):
            from design_graph.cli.build import main
            main()
        for line in out.read_text().splitlines():
            data = json.loads(line)
            assert len(data["content"]) <= max_c or data.get("level") == "screen"

    def test_chunk_prints_count_to_stdout(self, tmp_path, capsys):
        out = tmp_path / "chunks.jsonl"
        with patch("sys.argv", ["design-graph", "chunk", str(SIMPLE_HTML),
                                "--output", str(out)]):
            from design_graph.cli.build import main
            main()
        stdout = capsys.readouterr().out
        assert "chunk" in stdout.lower()
        assert any(c.isdigit() for c in stdout)

    def test_chunk_missing_file_exits_nonzero(self, tmp_path):
        ghost = tmp_path / "ghost.html"
        with patch("sys.argv", ["design-graph", "chunk", str(ghost)]):
            from design_graph.cli.build import main
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code != 0


# ── design-query ──────────────────────────────────────────────────────────────

class TestQueryCommand:
    """Run every subcommand against the real graph built by built_graph_dir."""

    @pytest.fixture(autouse=True)
    def _point_to_graph(self, built_graph_dir, monkeypatch):
        """Make design-query find the test graph via GRAPH_DIR env var."""
        graph_dir, _ = built_graph_dir
        monkeypatch.setenv("GRAPH_DIR", str(graph_dir))

    def _run_query(self, *argv):
        with patch("sys.argv", ["design-query", *argv]):
            from design_graph.cli.query import main
            main()

    def test_screens_lists_restaurants_page(self, capsys):
        self._run_query("screens")
        out = capsys.readouterr().out
        assert "RestaurantsPage" in out

    def test_tokens_returns_output(self, capsys):
        self._run_query("tokens")
        out = capsys.readouterr().out
        assert isinstance(out, str) and len(out) > 0

    def test_tokens_color_filter(self, capsys):
        self._run_query("tokens", "color")
        out = capsys.readouterr().out
        assert isinstance(out, str)

    def test_search_finds_btn_primary(self, capsys):
        self._run_query("search", "BtnPrimary")
        out = capsys.readouterr().out
        assert "BtnPrimary" in out

    def test_search_multi_word_query(self, capsys):
        self._run_query("search", "section", "card")
        out = capsys.readouterr().out
        assert isinstance(out, str)

    def test_inspect_btn_primary(self, capsys):
        self._run_query("inspect", "BtnPrimary")
        out = capsys.readouterr().out
        assert "BtnPrimary" in out

    def test_impact_returns_output(self, capsys):
        self._run_query("impact", "BtnPrimary")
        out = capsys.readouterr().out
        assert isinstance(out, str) and len(out) > 0

    def test_screen_restaurants_page(self, capsys):
        self._run_query("screen", "RestaurantsPage")
        out = capsys.readouterr().out
        assert "RestaurantsPage" in out

    def test_interactions_btn_primary(self, capsys):
        self._run_query("interactions", "BtnPrimary")
        out = capsys.readouterr().out
        assert isinstance(out, str)

    def test_children_returns_output(self, capsys):
        self._run_query("children", "BtnPrimary")
        out = capsys.readouterr().out
        assert isinstance(out, str)

    def test_verbose_flag_does_not_crash(self, capsys):
        self._run_query("screens", "--verbose")
        out = capsys.readouterr().out
        assert "RestaurantsPage" in out

    def test_no_graphs_prints_guidance(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("GRAPH_DIR", str(tmp_path / "empty"))
        with patch("sys.argv", ["design-query", "screens"]):
            from design_graph.cli.query import main
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code != 0
        err = capsys.readouterr().err
        assert "design-graph" in err.lower() or "no graphs" in err.lower()

    def test_unknown_command_exits_nonzero(self):
        with patch("sys.argv", ["design-query", "nonexistent_cmd"]):
            from design_graph.cli.query import main
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code != 0

    def test_help_exits_zero(self):
        with patch("sys.argv", ["design-query", "--help"]):
            from design_graph.cli.query import main
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 0
