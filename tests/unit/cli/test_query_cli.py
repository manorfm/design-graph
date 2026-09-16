"""
Unit tests for cli/query.py — command routing and argument parsing.

Verifies that each subcommand routes to the correct ToolDispatcher method
and that error paths (unknown command, missing args) exit cleanly.
Reader construction and real Kuzu interaction are deferred to the e2e tests.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch, call

import pytest

from design_graph.cli.query import (
    QueryCliArgs,
    parse_query_args,
    dispatch_query_command,
)


# ── parse_query_args ──────────────────────────────────────────────────────────

class TestParseQueryArgs:
    def test_screens_command_parsed(self):
        args = parse_query_args(["screens"])
        assert args.command == "screens"

    def test_tokens_command_without_category(self):
        args = parse_query_args(["tokens"])
        assert args.command == "tokens"
        assert args.category is None

    def test_tokens_command_with_color_category(self):
        args = parse_query_args(["tokens", "color"])
        assert args.command == "tokens"
        assert args.category == "color"

    def test_search_command_single_term(self):
        args = parse_query_args(["search", "BtnPrimary"])
        assert args.command == "search"
        assert args.query == "BtnPrimary"

    def test_search_command_multi_word_query(self):
        args = parse_query_args(["search", "section", "card"])
        assert args.command == "search"
        assert "section" in args.query and "card" in args.query

    def test_inspect_command(self):
        args = parse_query_args(["inspect", "BtnPrimary"])
        assert args.command == "inspect"
        assert args.name == "BtnPrimary"

    def test_impact_command(self):
        args = parse_query_args(["impact", "SectionCard"])
        assert args.command == "impact"
        assert args.name == "SectionCard"

    def test_screen_command(self):
        args = parse_query_args(["screen", "RestaurantsPage"])
        assert args.command == "screen"
        assert args.name == "RestaurantsPage"

    def test_interactions_command(self):
        args = parse_query_args(["interactions", "BtnPrimary"])
        assert args.command == "interactions"
        assert args.name == "BtnPrimary"

    def test_children_command(self):
        args = parse_query_args(["children", "CardProduct"])
        assert args.command == "children"
        assert args.name == "CardProduct"

    def test_verbose_flag_false_by_default(self):
        args = parse_query_args(["screens"])
        assert args.verbose is False

    def test_verbose_flag_enabled(self):
        args = parse_query_args(["screens", "--verbose"])
        assert args.verbose is True

    def test_document_can_be_selected_explicitly(self):
        args = parse_query_args(["--doc", "admin", "screens"])
        assert args.document == "admin"

    def test_database_path_can_be_selected_explicitly(self, tmp_path):
        args = parse_query_args(["--db", str(tmp_path / "admin.db"), "screens"])
        assert args.db_path == tmp_path / "admin.db"

    def test_no_command_raises_system_exit(self):
        with pytest.raises(SystemExit):
            parse_query_args([])

    def test_returns_query_cli_args(self):
        args = parse_query_args(["screens"])
        assert isinstance(args, QueryCliArgs)

    def test_help_lists_every_command(self, capsys):
        with pytest.raises(SystemExit) as exc:
            parse_query_args(["--help"])
        assert exc.value.code == 0
        output = capsys.readouterr().out
        for command in ("screens", "tokens", "search", "inspect", "impact", "screen",
                         "interactions", "children", "metrics"):
            assert command in output


# ── metrics command ───────────────────────────────────────────────────────────

class TestParseMetricsArgs:
    def test_metrics_command_parsed(self):
        args = parse_query_args(["metrics"])
        assert args.command == "metrics"

    def test_metrics_defaults_are_unset(self):
        args = parse_query_args(["metrics"])
        assert args.tool is None
        assert args.outcome is None
        assert args.since is None
        assert args.until is None
        assert args.limit is None
        assert args.raw is False

    def test_metrics_with_all_flags(self):
        args = parse_query_args([
            "metrics", "--tool", "search", "--outcome", "ok",
            "--since", "24h", "--until", "2026-01-01T00:00:00Z",
            "--limit", "10", "--raw",
        ])
        assert args.tool == "search"
        assert args.outcome == "ok"
        assert args.since == "24h"
        assert args.until == "2026-01-01T00:00:00Z"
        assert args.limit == 10
        assert args.raw is True

    def test_metrics_doc_filter_reuses_shared_flag(self):
        args = parse_query_args(["--doc", "toToggle", "metrics"])
        assert args.document == "toToggle"


# ── dispatch_query_command ────────────────────────────────────────────────────

class TestDispatchQueryCommand:
    """Verify each command calls the correct ToolDispatcher method."""

    def _args(self, command: str, name: str = "TestName",
              query: str = "test", category: str | None = None) -> QueryCliArgs:
        return QueryCliArgs(
            command=command, name=name, query=query,
            category=category, verbose=False,
        )

    def _mock_dispatcher_and_reader(self):
        reader     = MagicMock()
        dispatcher = MagicMock()
        dispatcher.list_screens.return_value = "## Screens"
        dispatcher.get_tokens.return_value = "## Tokens"
        dispatcher.tool_search.return_value = "## Results"
        dispatcher.get_component.return_value = "## Component"
        dispatcher.impact.return_value = "## Impact"
        dispatcher.get_screen.return_value = "## Screen"
        dispatcher.get_component_interactions.return_value = "## Interactions"
        dispatcher.get_component_children.return_value = "## Children"
        dispatcher.get_metrics.return_value = "## Métricas de uso"
        return dispatcher, reader

    def test_screens_calls_list_screens(self, capsys):
        dispatcher, reader = self._mock_dispatcher_and_reader()
        dispatch_query_command(self._args("screens"), dispatcher, reader)
        dispatcher.list_screens.assert_called_once()

    def test_tokens_without_category_passes_none(self, capsys):
        dispatcher, reader = self._mock_dispatcher_and_reader()
        args = QueryCliArgs(command="tokens", name="", query="", category=None, verbose=False)
        dispatch_query_command(args, dispatcher, reader)
        dispatcher.get_tokens.assert_called_once_with(reader, None)

    def test_tokens_with_category_passes_category(self, capsys):
        dispatcher, reader = self._mock_dispatcher_and_reader()
        args = QueryCliArgs(command="tokens", name="", query="", category="color", verbose=False)
        dispatch_query_command(args, dispatcher, reader)
        dispatcher.get_tokens.assert_called_once_with(reader, "color")

    def test_search_calls_tool_search_with_query(self, capsys):
        dispatcher, reader = self._mock_dispatcher_and_reader()
        args = QueryCliArgs(command="search", name="", query="sectioncard", category=None, verbose=False)
        dispatch_query_command(args, dispatcher, reader)
        dispatcher.tool_search.assert_called_once_with("sectioncard")

    def test_inspect_calls_get_component_with_name(self, capsys):
        dispatcher, reader = self._mock_dispatcher_and_reader()
        dispatch_query_command(self._args("inspect", name="BtnPrimary"), dispatcher, reader)
        dispatcher.get_component.assert_called_once_with(reader, "BtnPrimary")

    def test_impact_calls_impact_with_name(self, capsys):
        dispatcher, reader = self._mock_dispatcher_and_reader()
        dispatch_query_command(self._args("impact", name="SectionCard"), dispatcher, reader)
        dispatcher.impact.assert_called_once_with(reader, "SectionCard")

    def test_screen_calls_get_screen_with_name(self, capsys):
        dispatcher, reader = self._mock_dispatcher_and_reader()
        dispatch_query_command(self._args("screen", name="RestaurantsPage"), dispatcher, reader)
        dispatcher.get_screen.assert_called_once_with(reader, "RestaurantsPage")

    def test_interactions_calls_get_component_interactions(self, capsys):
        dispatcher, reader = self._mock_dispatcher_and_reader()
        dispatch_query_command(self._args("interactions", name="BtnPrimary"), dispatcher, reader)
        dispatcher.get_component_interactions.assert_called_once_with(reader, "BtnPrimary")

    def test_children_calls_get_component_children(self, capsys):
        dispatcher, reader = self._mock_dispatcher_and_reader()
        dispatch_query_command(self._args("children", name="CardProduct"), dispatcher, reader)
        dispatcher.get_component_children.assert_called_once_with(reader, "CardProduct")

    def test_metrics_calls_get_metrics_with_all_args(self, capsys):
        dispatcher, reader = self._mock_dispatcher_and_reader()
        args = QueryCliArgs(
            command="metrics", name="", query="", category=None, verbose=False,
            document="toToggle", tool="search", outcome="ok",
            since="24h", until="2026-01-01T00:00:00Z", limit=10, raw=True,
        )
        dispatch_query_command(args, dispatcher, reader)
        dispatcher.get_metrics.assert_called_once_with(
            doc="toToggle", tool="search", outcome="ok",
            since="24h", until="2026-01-01T00:00:00Z", limit=10, raw=True,
        )

    def test_metrics_output_is_printed(self, capsys):
        dispatcher, reader = self._mock_dispatcher_and_reader()
        args = QueryCliArgs(command="metrics", name="", query="", category=None, verbose=False)
        dispatch_query_command(args, dispatcher, reader)
        assert "Métricas de uso" in capsys.readouterr().out

    def test_unknown_command_raises_system_exit(self):
        dispatcher, reader = self._mock_dispatcher_and_reader()
        args = QueryCliArgs(command="totally_unknown", name="", query="", category=None, verbose=False)
        with pytest.raises(SystemExit) as exc_info:
            dispatch_query_command(args, dispatcher, reader)
        assert exc_info.value.code != 0

    def test_output_is_printed_to_stdout(self, capsys):
        dispatcher, reader = self._mock_dispatcher_and_reader()
        dispatch_query_command(self._args("screens"), dispatcher, reader)
        captured = capsys.readouterr()
        assert "Screens" in captured.out
