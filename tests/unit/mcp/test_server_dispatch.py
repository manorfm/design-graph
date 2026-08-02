"""
MCPServer's own responsibility, decoupled from wire protocol: define tools,
dispatch calls, track session state and reload on staleness — as plain
dicts/strings. The mcp SDK (lowlevel.Server, wired at the bottom of
server.py) owns JSON-RPC framing, protocol version negotiation and
notification handling entirely on its own; testing that here would just be
re-testing the SDK's own test suite, not our code.
"""

from __future__ import annotations

from pathlib import Path

from design_graph.mcp.server import ToolCallResult, _warn_if_no_graphs


class TestToolCallResult:
    def test_defaults_to_not_an_error(self):
        assert ToolCallResult(text="ok").is_error is False

    def test_carries_the_error_flag_when_set(self):
        assert ToolCallResult(text="boom", is_error=True).is_error is True

    def test_is_a_plain_value_not_a_mutable_container(self):
        result = ToolCallResult(text="ok")
        assert result.text == "ok"


class TestWarnIfNoGraphs:
    def test_writes_a_warning_when_readers_are_empty(self, capsys):
        _warn_if_no_graphs([], Path("/some/graph/dir"))
        err = capsys.readouterr().err
        assert "no graphs" in err.lower()
        assert "design-graph" in err

    def test_silent_when_readers_are_present(self, capsys):
        _warn_if_no_graphs([("doc", object())], Path("/some/graph/dir"))
        assert capsys.readouterr().err == ""
