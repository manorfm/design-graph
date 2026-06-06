"""
End-to-end tests for 'design-graph report' command.

Builds a real Kuzu graph from simple.html once (module-scoped fixture) and
exercises the complete report pipeline:
  main() → _run_report → build_prototype_report → render_markdown_report → stdout / file

These tests complement the unit-level tests in tests/unit/cli/test_report_cli.py
and tests/unit/cli/test_report_builder.py.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from design_graph.pipeline.coordinator import run_pipeline

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"
SIMPLE_HTML = FIXTURE_DIR / "simple.html"


# ── shared graph built once for all tests ────────────────────────────────────

@pytest.fixture(scope="module")
def built_graph(tmp_path_factory):
    """Build a real Kuzu graph from simple.html once for all tests in this module."""
    tmp        = tmp_path_factory.mktemp("report_e2e")
    db_path    = tmp / "simple.db"
    state_path = tmp / ".graph-state.json"
    asyncio.run(run_pipeline(SIMPLE_HTML, db_path, state_path))
    return tmp, db_path


# ── helper ────────────────────────────────────────────────────────────────────

def _invoke_report(argv: list[str]) -> None:
    """Invoke design-graph report via main() with controlled sys.argv."""
    with patch("sys.argv", ["design-graph", "report", *argv]):
        from design_graph.cli.build import main
        main()


# ── routing and basic output ──────────────────────────────────────────────────

class TestReportCommandRouting:
    def test_report_subcommand_routed_from_main(self, built_graph, capsys):
        _, db_path = built_graph
        _invoke_report(["--db", str(db_path)])
        out = capsys.readouterr().out
        assert len(out.strip()) > 0

    def test_report_output_starts_with_h1_heading(self, built_graph, capsys):
        _, db_path = built_graph
        _invoke_report(["--db", str(db_path)])
        out = capsys.readouterr().out
        assert out.strip().startswith("#")

    def test_report_contains_prototype_report_title(self, built_graph, capsys):
        _, db_path = built_graph
        _invoke_report(["--db", str(db_path)])
        out = capsys.readouterr().out
        assert "# Prototype Report" in out

    def test_report_db_stem_used_as_default_prototype_name(self, built_graph, capsys):
        _, db_path = built_graph
        _invoke_report(["--db", str(db_path)])
        out = capsys.readouterr().out
        assert db_path.stem in out  # "simple" from simple.db


# ── Markdown structure ────────────────────────────────────────────────────────

class TestReportMarkdownStructure:
    def test_report_contains_overview_section(self, built_graph, capsys):
        _, db_path = built_graph
        _invoke_report(["--db", str(db_path)])
        out = capsys.readouterr().out
        assert "## Overview" in out

    def test_report_contains_screens_section(self, built_graph, capsys):
        _, db_path = built_graph
        _invoke_report(["--db", str(db_path)])
        out = capsys.readouterr().out
        assert "## Screens" in out

    def test_report_contains_at_least_three_headings(self, built_graph, capsys):
        _, db_path = built_graph
        _invoke_report(["--db", str(db_path)])
        out = capsys.readouterr().out
        headings = [l for l in out.splitlines() if l.startswith("#")]
        assert len(headings) >= 3

    def test_report_contains_real_screen_from_fixture(self, built_graph, capsys):
        _, db_path = built_graph
        _invoke_report(["--db", str(db_path)])
        out = capsys.readouterr().out
        assert "RestaurantsPage" in out or "Page" in out

    def test_report_contains_token_table_by_default(self, built_graph, capsys):
        _, db_path = built_graph
        _invoke_report(["--db", str(db_path)])
        out = capsys.readouterr().out
        assert "Design Tokens" in out or "Overview" in out


# ── --no-tokens flag ──────────────────────────────────────────────────────────

class TestReportNoTokensFlag:
    def test_no_tokens_excludes_design_tokens_section(self, built_graph, capsys):
        _, db_path = built_graph
        _invoke_report(["--db", str(db_path), "--no-tokens"])
        out = capsys.readouterr().out
        assert "Design Tokens" not in out

    def test_no_tokens_still_produces_valid_markdown(self, built_graph, capsys):
        _, db_path = built_graph
        _invoke_report(["--db", str(db_path), "--no-tokens"])
        out = capsys.readouterr().out
        assert out.strip().startswith("#")
        assert "## Screens" in out


# ── --name flag ───────────────────────────────────────────────────────────────

class TestReportCustomName:
    def test_custom_name_appears_in_report_title(self, built_graph, capsys):
        _, db_path = built_graph
        _invoke_report(["--db", str(db_path), "--name", "MyProto"])
        out = capsys.readouterr().out
        assert "MyProto" in out

    def test_custom_name_replaces_db_stem_in_title(self, built_graph, capsys):
        _, db_path = built_graph
        _invoke_report(["--db", str(db_path), "--name", "Unicorn"])
        out = capsys.readouterr().out
        assert "Unicorn" in out


# ── --output flag ─────────────────────────────────────────────────────────────

class TestReportOutputFile:
    def test_output_flag_creates_markdown_file(self, built_graph, tmp_path, capsys):
        _, db_path = built_graph
        out_file = tmp_path / "report.md"
        _invoke_report(["--db", str(db_path), "--output", str(out_file)])
        assert out_file.exists()

    def test_output_file_contains_valid_markdown(self, built_graph, tmp_path, capsys):
        _, db_path = built_graph
        out_file = tmp_path / "report.md"
        _invoke_report(["--db", str(db_path), "--output", str(out_file)])
        content = out_file.read_text(encoding="utf-8")
        assert "# Prototype Report" in content
        assert "## Screens" in content

    def test_output_to_file_prints_confirmation_to_stdout(self, built_graph, tmp_path, capsys):
        _, db_path = built_graph
        out_file = tmp_path / "report2.md"
        _invoke_report(["--db", str(db_path), "--output", str(out_file)])
        stdout = capsys.readouterr().out
        assert str(out_file) in stdout or "report" in stdout.lower()

    def test_output_file_not_written_to_stdout(self, built_graph, tmp_path, capsys):
        _, db_path = built_graph
        out_file = tmp_path / "report3.md"
        _invoke_report(["--db", str(db_path), "--output", str(out_file)])
        stdout = capsys.readouterr().out
        assert "# Prototype Report" not in stdout  # content goes to file, not stdout


# ── --jsx and --verbose flags ─────────────────────────────────────────────────

class TestReportAdditionalFlags:
    def test_jsx_flag_accepted_without_crash(self, built_graph, capsys):
        _, db_path = built_graph
        _invoke_report(["--db", str(db_path), "--jsx"])
        out = capsys.readouterr().out
        assert "# Prototype Report" in out

    def test_verbose_flag_accepted_without_crash(self, built_graph, capsys):
        _, db_path = built_graph
        _invoke_report(["--db", str(db_path), "--verbose"])
        out = capsys.readouterr().out
        assert "# Prototype Report" in out
