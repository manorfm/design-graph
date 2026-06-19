"""
Unit tests for cli/build.py — argument parsing, flag handling, and output formatting.

These tests exercise the argument parser and business-logic plumbing without
touching the file system or running the real pipeline. IO-heavy paths are
covered by tests/integration/test_cli_end_to_end.py.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from design_graph.cli.build import (
    BuildCliArgs,
    parse_build_args,
    parse_chunk_args,
    ChunkCliArgs,
    main,
    parse_database_args,
)


# ── parse_build_args ──────────────────────────────────────────────────────────

class TestParseBuildArgs:
    def test_minimal_args_uses_html_path(self, tmp_path):
        html = tmp_path / "proto.html"
        args = parse_build_args([str(html)])
        assert args.html_path == html

    def test_diff_flag_false_by_default(self, tmp_path):
        html = tmp_path / "proto.html"
        args = parse_build_args([str(html)])
        assert args.show_diff is False

    def test_diff_flag_enables_diff(self, tmp_path):
        html = tmp_path / "proto.html"
        args = parse_build_args([str(html), "--diff"])
        assert args.show_diff is True

    def test_force_flag_false_by_default(self, tmp_path):
        html = tmp_path / "proto.html"
        args = parse_build_args([str(html)])
        assert args.force is False

    def test_force_flag_enables_force(self, tmp_path):
        html = tmp_path / "proto.html"
        args = parse_build_args([str(html), "--force"])
        assert args.force is True

    def test_db_flag_sets_custom_db_path(self, tmp_path):
        html = tmp_path / "proto.html"
        db   = tmp_path / "custom.db"
        args = parse_build_args([str(html), "--db", str(db)])
        assert args.db_path == db

    def test_db_path_is_none_when_not_provided(self, tmp_path):
        html = tmp_path / "proto.html"
        args = parse_build_args([str(html)])
        assert args.db_path is None

    def test_verbose_flag_false_by_default(self, tmp_path):
        html = tmp_path / "proto.html"
        args = parse_build_args([str(html)])
        assert args.verbose is False

    def test_verbose_flag_sets_verbose(self, tmp_path):
        html = tmp_path / "proto.html"
        args = parse_build_args([str(html), "--verbose"])
        assert args.verbose is True

    def test_quiet_flag_false_by_default(self, tmp_path):
        html = tmp_path / "proto.html"
        args = parse_build_args([str(html)])
        assert args.quiet is False

    def test_quiet_flag_sets_quiet(self, tmp_path):
        html = tmp_path / "proto.html"
        args = parse_build_args([str(html), "--quiet"])
        assert args.quiet is True

    def test_all_flags_combined(self, tmp_path):
        html = tmp_path / "proto.html"
        db   = tmp_path / "out.db"
        args = parse_build_args([str(html), "--diff", "--force", "--db", str(db), "--verbose"])
        assert args.show_diff is True
        assert args.force is True
        assert args.db_path == db
        assert args.verbose is True

    def test_returns_build_cli_args_dataclass(self, tmp_path):
        html = tmp_path / "proto.html"
        args = parse_build_args([str(html)])
        assert isinstance(args, BuildCliArgs)

    def test_missing_html_path_raises_system_exit(self):
        with pytest.raises(SystemExit):
            parse_build_args([])

    def test_unknown_flag_raises_system_exit(self, tmp_path):
        html = tmp_path / "proto.html"
        with pytest.raises(SystemExit):
            parse_build_args([str(html), "--unknown-flag"])


# ── parse_chunk_args ──────────────────────────────────────────────────────────

class TestParseChunkArgs:
    def test_minimal_args_uses_html_path(self, tmp_path):
        html = tmp_path / "proto.html"
        args = parse_chunk_args([str(html)])
        assert args.html_path == html

    def test_output_defaults_to_jsonl_next_to_input(self, tmp_path):
        html = tmp_path / "proto.html"
        args = parse_chunk_args([str(html)])
        assert args.output_path == html.with_suffix(".jsonl")

    def test_output_flag_sets_custom_path(self, tmp_path):
        html = tmp_path / "proto.html"
        out  = tmp_path / "chunks.jsonl"
        args = parse_chunk_args([str(html), "--output", str(out)])
        assert args.output_path == out

    def test_max_chars_defaults_to_12000(self, tmp_path):
        html = tmp_path / "proto.html"
        args = parse_chunk_args([str(html)])
        assert args.max_chars == 12_000

    def test_max_chars_flag_sets_custom_value(self, tmp_path):
        html = tmp_path / "proto.html"
        args = parse_chunk_args([str(html), "--max-chars", "8000"])
        assert args.max_chars == 8_000

    def test_verbose_flag_available(self, tmp_path):
        html = tmp_path / "proto.html"
        args = parse_chunk_args([str(html), "--verbose"])
        assert args.verbose is True

    def test_returns_chunk_cli_args_dataclass(self, tmp_path):
        html = tmp_path / "proto.html"
        args = parse_chunk_args([str(html)])
        assert isinstance(args, ChunkCliArgs)

    def test_missing_html_raises_system_exit(self):
        with pytest.raises(SystemExit):
            parse_chunk_args([])


# ── BuildCliArgs dataclass ────────────────────────────────────────────────────

class TestBuildCliArgsContract:
    def test_has_all_required_fields(self, tmp_path):
        args = BuildCliArgs(
            html_path=tmp_path / "p.html",
            db_path=None,
            show_diff=False,
            force=False,
            verbose=False,
            quiet=False,
        )
        assert hasattr(args, "html_path")
        assert hasattr(args, "db_path")
        assert hasattr(args, "show_diff")
        assert hasattr(args, "force")
        assert hasattr(args, "verbose")
        assert hasattr(args, "quiet")


class TestMainHelp:
    def test_lists_every_subcommand(self, capsys):
        with patch("sys.argv", ["design-graph", "--help"]):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 0
        output = capsys.readouterr().out
        for command in ("chunk", "status", "validate", "report", "db"):
            assert command in output
        for option in ("--db", "--diff", "--force", "--verbose", "--quiet", "--json"):
            assert option in output


class TestDatabaseArgs:
    def test_list_supports_json(self):
        args = parse_database_args(["list", "--json"])
        assert args.action == "list"
        assert args.json_output is True

    def test_use_requires_document(self):
        args = parse_database_args(["use", "prototype"])
        assert args.action == "use"
        assert args.document == "prototype"

    def test_info_accepts_document(self):
        args = parse_database_args(["info", "prototype"])
        assert args.document == "prototype"

    def test_remove_supports_force(self):
        args = parse_database_args(["remove", "prototype", "--force"])
        assert args.action == "remove"
        assert args.document == "prototype"
        assert args.force is True

    def test_prune_supports_dry_run(self):
        args = parse_database_args(["prune", "--dry-run"])
        assert args.action == "prune"
        assert args.dry_run is True

    def test_list_command_reports_available_databases(self, tmp_path, monkeypatch, capsys):
        (tmp_path / "admin.db").mkdir()
        monkeypatch.setenv("GRAPH_DIR", str(tmp_path))
        monkeypatch.delenv("DESIGN_GRAPH_DOC", raising=False)
        with patch("sys.argv", ["design-graph", "db", "list"]):
            main()
        assert "admin" in capsys.readouterr().out


# ── ChunkCliArgs dataclass ────────────────────────────────────────────────────

class TestChunkCliArgsContract:
    def test_has_all_required_fields(self, tmp_path):
        args = ChunkCliArgs(
            html_path=tmp_path / "p.html",
            output_path=tmp_path / "out.jsonl",
            max_chars=12_000,
            verbose=False,
        )
        assert hasattr(args, "html_path")
        assert hasattr(args, "output_path")
        assert hasattr(args, "max_chars")
        assert hasattr(args, "verbose")
