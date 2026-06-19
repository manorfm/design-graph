"""
Unit tests for --json flag on design-graph build and design-graph validate.

Machine-readable JSON output enables CI pipelines to assert on graph metrics
without parsing human-formatted text. Format: newline-delimited JSON on stdout.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from design_graph.cli.build import BuildCliArgs, parse_build_args


# ── parse_build_args: --json flag ─────────────────────────────────────────────

class TestJsonFlag:
    def test_json_false_by_default(self, tmp_path):
        args = parse_build_args([str(tmp_path / "p.html")])
        assert args.json_output is False

    def test_json_flag_enabled(self, tmp_path):
        args = parse_build_args([str(tmp_path / "p.html"), "--json"])
        assert args.json_output is True

    def test_json_and_quiet_can_coexist(self, tmp_path):
        args = parse_build_args([str(tmp_path / "p.html"), "--json", "--quiet"])
        assert args.json_output is True
        assert args.quiet is True

    def test_build_cli_args_has_json_output_field(self, tmp_path):
        args = BuildCliArgs(
            html_path=tmp_path / "p.html",
            db_path=None, prototype_name=None, show_diff=False, force=False,
            verbose=False, quiet=False, json_output=True,
        )
        assert args.json_output is True


# ── JSON output format ────────────────────────────────────────────────────────

class TestBuildJsonOutput:
    FIXTURE = Path(__file__).parent.parent.parent / "fixtures" / "simple.html"

    def test_json_output_is_valid_json(self, tmp_path, capsys):
        db = tmp_path / "out.db"
        with patch("sys.argv", ["design-graph", str(self.FIXTURE),
                                "--db", str(db), "--json"]):
            from design_graph.cli.build import main
            main()
        out = capsys.readouterr().out.strip()
        data = json.loads(out)
        assert isinstance(data, dict)

    def test_json_output_has_required_fields(self, tmp_path, capsys):
        db = tmp_path / "out.db"
        with patch("sys.argv", ["design-graph", str(self.FIXTURE),
                                "--db", str(db), "--json"]):
            from design_graph.cli.build import main
            main()
        data = json.loads(capsys.readouterr().out)
        required = {"status", "screens", "components", "tokens",
                    "sections", "interactions", "contains_rels", "duration_seconds"}
        assert required.issubset(data.keys()), f"Missing fields: {required - data.keys()}"

    def test_json_status_is_built(self, tmp_path, capsys):
        db = tmp_path / "out.db"
        with patch("sys.argv", ["design-graph", str(self.FIXTURE),
                                "--db", str(db), "--json"]):
            from design_graph.cli.build import main
            main()
        data = json.loads(capsys.readouterr().out)
        assert data["status"] == "built"

    def test_json_skipped_status_when_unchanged(self, tmp_path, capsys):
        db = tmp_path / "out.db"
        # First build via CLI (creates state file at db.parent / .graph-state.json)
        with patch("sys.argv", ["design-graph", str(self.FIXTURE),
                                "--db", str(db), "--json"]):
            from design_graph.cli.build import main
            main()
        capsys.readouterr()  # clear first build output
        # Second build — same file, same state path → should skip
        with patch("sys.argv", ["design-graph", str(self.FIXTURE),
                                "--db", str(db), "--json"]):
            main()
        data = json.loads(capsys.readouterr().out)
        assert data["status"] == "skipped"

    def test_json_screens_is_integer(self, tmp_path, capsys):
        db = tmp_path / "out.db"
        with patch("sys.argv", ["design-graph", str(self.FIXTURE),
                                "--db", str(db), "--json"]):
            from design_graph.cli.build import main
            main()
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data["screens"], int)
        assert data["screens"] >= 1

    def test_json_missing_file_outputs_error_json(self, tmp_path, capsys):
        ghost = tmp_path / "ghost.html"
        with patch("sys.argv", ["design-graph", str(ghost), "--json"]):
            from design_graph.cli.build import main
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code != 0
        # On error, stderr should have the message (stdout may be empty or error JSON)


# ── validate command ──────────────────────────────────────────────────────────

from design_graph.cli.validate import (
    GraphValidationReport,
    GraphViolation,
    ValidationSeverity,
    validate_graph,
)


class TestValidateCommand:
    FIXTURE = Path(__file__).parent.parent.parent / "fixtures" / "simple.html"

    def test_validate_returns_report(self, tmp_path):
        import asyncio
        from design_graph.pipeline.coordinator import run_pipeline
        db = tmp_path / "v.db"
        asyncio.run(run_pipeline(self.FIXTURE, db, tmp_path / ".state.json"))

        report = validate_graph(db)
        assert isinstance(report, GraphValidationReport)

    def test_valid_graph_has_no_errors(self, tmp_path):
        import asyncio
        from design_graph.pipeline.coordinator import run_pipeline
        db = tmp_path / "v.db"
        asyncio.run(run_pipeline(self.FIXTURE, db, tmp_path / ".state.json"))

        report = validate_graph(db)
        errors = [v for v in report.violations if v.severity == ValidationSeverity.ERROR]
        assert not errors, f"Unexpected errors in valid graph: {errors}"

    def test_report_has_summary_counts(self, tmp_path):
        import asyncio
        from design_graph.pipeline.coordinator import run_pipeline
        db = tmp_path / "v.db"
        asyncio.run(run_pipeline(self.FIXTURE, db, tmp_path / ".state.json"))

        report = validate_graph(db)
        assert hasattr(report, "node_counts")
        assert isinstance(report.node_counts, dict)

    def test_missing_db_produces_error_violation(self, tmp_path):
        report = validate_graph(tmp_path / "missing.db")
        assert report.violations
        assert any(v.severity == ValidationSeverity.ERROR for v in report.violations)


class TestGraphViolation:
    def test_violation_has_required_fields(self):
        v = GraphViolation(
            severity=ValidationSeverity.ERROR,
            check_name="orphaned_components",
            message="Found 3 orphaned components",
            details={"names": ["OldComp", "Ghost"]},
        )
        assert v.severity == ValidationSeverity.ERROR
        assert v.check_name == "orphaned_components"
        assert isinstance(v.message, str)

    def test_warning_severity(self):
        v = GraphViolation(
            severity=ValidationSeverity.WARNING,
            check_name="no_sections",
            message="Screen has no sections",
            details={},
        )
        assert v.severity == ValidationSeverity.WARNING


class TestValidateCommandCli:
    FIXTURE = Path(__file__).parent.parent.parent / "fixtures" / "simple.html"

    def test_validate_subcommand_from_main(self, tmp_path, capsys, monkeypatch):
        import asyncio
        from design_graph.pipeline.coordinator import run_pipeline
        db = tmp_path / "v.db"
        asyncio.run(run_pipeline(self.FIXTURE, db, tmp_path / ".state.json"))

        with patch("sys.argv", ["design-graph", "validate", "--db", str(db)]):
            from design_graph.cli.build import main
            main()
        out = capsys.readouterr().out
        assert isinstance(out, str) and len(out) > 0

    def test_validate_json_output(self, tmp_path, capsys, monkeypatch):
        import asyncio
        from design_graph.pipeline.coordinator import run_pipeline
        db = tmp_path / "v.db"
        asyncio.run(run_pipeline(self.FIXTURE, db, tmp_path / ".state.json"))

        with patch("sys.argv", ["design-graph", "validate", "--db", str(db), "--json"]):
            from design_graph.cli.build import main
            main()
        out = capsys.readouterr().out.strip()
        data = json.loads(out)
        assert "status" in data
        assert "violations" in data
