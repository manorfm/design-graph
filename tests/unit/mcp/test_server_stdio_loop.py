"""
Tests for MCPServer.run() — the stdio event loop.

The run() method reads JSON-RPC messages from stdin line by line and writes
responses to stdout. These tests simulate stdin via StringIO and capture
stdout to verify the complete server loop without network or file I/O.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from design_graph.mcp.server import MCPServer


# ── helpers ───────────────────────────────────────────────────────────────────

class _StubReader:
    def list_screens(self):          return [{"name": "Screen1", "component_count": 1, "sections_count": 0, "top_components": []}]
    def get_screen(self, n):         return None
    def get_component(self, n):      return None
    def get_component_children(self, n): return []
    def get_component_parents(self, n):  return []
    def find_screens_using_comp_transitively(self, n): return []
    def get_section(self, s, h):     return None
    def get_tokens(self, cat=None):  return []
    def find_token_usage(self, v):   return []
    def get_interactions(self, n):   return []
    def get_full_jsx(self, n):       return ""
    def get_impact(self, n):         return {"found": False}
    def count_nodes(self):           return {}


def _run_server_with_input(lines: list[str], readers=None) -> list[dict]:
    """
    Feed lines into MCPServer.run() via mocked stdin.
    Returns list of parsed JSON response objects written to stdout.
    """
    if readers is None:
        readers = [("doc1", _StubReader())]
    server = MCPServer(readers)
    stdin_text  = "\n".join(lines) + "\n"
    stdout_buf  = io.StringIO()

    with patch("sys.stdin", io.StringIO(stdin_text)):
        with patch("sys.stdout", stdout_buf):
            server.run()

    output = stdout_buf.getvalue()
    return [json.loads(line) for line in output.splitlines() if line.strip()]


# ── run() loop ────────────────────────────────────────────────────────────────

class TestServerStdioLoop:
    def test_single_initialize_request_produces_response(self):
        msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        responses = _run_server_with_input([msg])
        assert len(responses) == 1
        assert responses[0]["result"]["protocolVersion"] == "2024-11-05"

    def test_multiple_requests_produce_multiple_responses(self):
        msgs = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
        ]
        responses = _run_server_with_input(msgs)
        assert len(responses) == 2

    def test_empty_lines_are_ignored(self):
        msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        responses = _run_server_with_input(["", "   ", msg, "", ""])
        assert len(responses) == 1

    def test_malformed_json_line_is_skipped_silently(self):
        valid = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        responses = _run_server_with_input(["not valid json {{{{", valid])
        assert len(responses) == 1

    def test_notification_produces_no_response(self):
        """notifications/initialized must NOT write a response (returns None)."""
        notif = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        init  = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        responses = _run_server_with_input([notif, init])
        assert len(responses) == 1  # only the initialize response

    def test_tools_list_response_written_to_stdout(self):
        msg = json.dumps({"jsonrpc": "2.0", "id": 5, "method": "tools/list", "params": {}})
        responses = _run_server_with_input([msg])
        assert len(responses) == 1
        tool_names = [t["name"] for t in responses[0]["result"]["tools"]]
        assert "list_screens" in tool_names

    def test_response_ids_match_request_ids(self):
        msgs = [
            json.dumps({"jsonrpc": "2.0", "id": 7, "method": "initialize", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "id": 8, "method": "tools/list", "params": {}}),
        ]
        responses = _run_server_with_input(msgs)
        ids = {r["id"] for r in responses}
        assert 7 in ids
        assert 8 in ids

    def test_tools_call_produces_text_response(self):
        msg = json.dumps({
            "jsonrpc": "2.0", "id": 3,
            "method": "tools/call",
            "params": {"name": "list_screens", "arguments": {}},
        })
        responses = _run_server_with_input([msg])
        assert len(responses) == 1
        text = responses[0]["result"]["content"][0]["text"]
        assert isinstance(text, str)

    def test_unknown_method_produces_error_32601(self):
        msg = json.dumps({"jsonrpc": "2.0", "id": 9, "method": "foo/bar", "params": {}})
        responses = _run_server_with_input([msg])
        assert responses[0]["error"]["code"] == -32601

    def test_stdin_close_exits_loop_cleanly(self):
        """run() should return normally when stdin ends (no remaining lines)."""
        responses = _run_server_with_input([])  # empty stdin
        assert responses == []


# ── main() startup ────────────────────────────────────────────────────────────

class TestServerMain:
    def test_main_writes_no_graphs_warning_when_dir_empty(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("GRAPH_DIR", str(tmp_path))
        with patch("sys.stdin", io.StringIO("")):
            from design_graph.mcp.server import main
            main()
        err = capsys.readouterr().err
        assert "no graphs" in err.lower() or "design-graph" in err.lower()

    def test_main_runs_without_crash_when_graph_dir_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GRAPH_DIR", str(tmp_path / "nonexistent_dir"))
        with patch("sys.stdin", io.StringIO("")):
            from design_graph.mcp.server import main
            main()  # must not raise

    def test_main_skips_corrupt_db_with_warning(self, tmp_path, monkeypatch, capsys):
        bad_db = tmp_path / "corrupt.db"
        bad_db.write_bytes(b"this is not a kuzu database at all")
        monkeypatch.setenv("GRAPH_DIR", str(tmp_path))
        with patch("sys.stdin", io.StringIO("")):
            from design_graph.mcp.server import main
            main()
        err = capsys.readouterr().err
        assert "failed" in err.lower() or "no graphs" in err.lower() or "corrupt" in err.lower()
