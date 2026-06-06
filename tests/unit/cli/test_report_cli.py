"""
Unit tests for 'design-graph report' CLI argument parsing.

Verifies ReportCliArgs and parse_report_args in pure isolation — no file
system writes, no Kuzu connection. Integration with a real graph is in
tests/integration/test_report_e2e.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from design_graph.cli.build import ReportCliArgs, parse_report_args


# ── ReportCliArgs dataclass contract ─────────────────────────────────────────

class TestReportCliArgsContract:
    def test_has_db_path_field(self):
        args = ReportCliArgs(
            db_path=None, output_path=None, prototype_name=None,
            include_tokens=True, include_jsx=False, verbose=False,
        )
        assert hasattr(args, "db_path")

    def test_has_output_path_field(self):
        args = ReportCliArgs(
            db_path=None, output_path=None, prototype_name=None,
            include_tokens=True, include_jsx=False, verbose=False,
        )
        assert hasattr(args, "output_path")

    def test_has_prototype_name_field(self):
        args = ReportCliArgs(
            db_path=None, output_path=None, prototype_name="myapp",
            include_tokens=True, include_jsx=False, verbose=False,
        )
        assert args.prototype_name == "myapp"

    def test_has_include_tokens_field(self):
        args = ReportCliArgs(
            db_path=None, output_path=None, prototype_name=None,
            include_tokens=False, include_jsx=False, verbose=False,
        )
        assert args.include_tokens is False

    def test_has_include_jsx_field(self):
        args = ReportCliArgs(
            db_path=None, output_path=None, prototype_name=None,
            include_tokens=True, include_jsx=True, verbose=False,
        )
        assert args.include_jsx is True

    def test_has_verbose_field(self):
        args = ReportCliArgs(
            db_path=None, output_path=None, prototype_name=None,
            include_tokens=True, include_jsx=False, verbose=True,
        )
        assert args.verbose is True


# ── parse_report_args defaults ────────────────────────────────────────────────

class TestParseReportArgsDefaults:
    def test_db_path_is_none_when_not_provided(self):
        args = parse_report_args([])
        assert args.db_path is None

    def test_output_path_is_none_when_not_provided(self):
        args = parse_report_args([])
        assert args.output_path is None

    def test_prototype_name_is_none_when_not_provided(self):
        args = parse_report_args([])
        assert args.prototype_name is None

    def test_include_tokens_is_true_by_default(self):
        args = parse_report_args([])
        assert args.include_tokens is True

    def test_include_jsx_is_false_by_default(self):
        args = parse_report_args([])
        assert args.include_jsx is False

    def test_verbose_is_false_by_default(self):
        args = parse_report_args([])
        assert args.verbose is False

    def test_returns_report_cli_args_instance(self):
        assert isinstance(parse_report_args([]), ReportCliArgs)


# ── parse_report_args flag parsing ───────────────────────────────────────────

class TestParseReportArgsFlags:
    def test_db_flag_sets_path(self, tmp_path):
        db = tmp_path / "x.db"
        args = parse_report_args(["--db", str(db)])
        assert args.db_path == db

    def test_output_flag_sets_path(self, tmp_path):
        out = tmp_path / "report.md"
        args = parse_report_args(["--output", str(out)])
        assert args.output_path == out

    def test_name_flag_sets_prototype_name(self):
        args = parse_report_args(["--name", "iPede"])
        assert args.prototype_name == "iPede"

    def test_no_tokens_disables_include_tokens(self):
        args = parse_report_args(["--no-tokens"])
        assert args.include_tokens is False

    def test_jsx_enables_include_jsx(self):
        args = parse_report_args(["--jsx"])
        assert args.include_jsx is True

    def test_verbose_sets_verbose(self):
        args = parse_report_args(["--verbose"])
        assert args.verbose is True

    def test_all_flags_combined(self, tmp_path):
        db  = tmp_path / "x.db"
        out = tmp_path / "r.md"
        args = parse_report_args([
            "--db", str(db), "--output", str(out),
            "--name", "iPede", "--no-tokens", "--jsx", "--verbose",
        ])
        assert args.db_path       == db
        assert args.output_path   == out
        assert args.prototype_name == "iPede"
        assert args.include_tokens is False
        assert args.include_jsx    is True
        assert args.verbose        is True

    def test_unknown_flag_raises_system_exit(self):
        with pytest.raises(SystemExit):
            parse_report_args(["--unknown-flag"])

    def test_db_path_is_path_object(self, tmp_path):
        db   = tmp_path / "x.db"
        args = parse_report_args(["--db", str(db)])
        assert isinstance(args.db_path, Path)

    def test_output_path_is_path_object(self, tmp_path):
        out  = tmp_path / "r.md"
        args = parse_report_args(["--output", str(out)])
        assert isinstance(args.output_path, Path)
