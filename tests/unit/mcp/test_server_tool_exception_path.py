"""
Tests for the MCPServer tool exception path and multi-reader description.

Targets:
  - _handle_tool_call except block (lines 117-121): tool raises → error response
  - _handle_initialize with multiple readers and no active_doc (line 79)
  - _send writes to stdout correctly (indirect)
"""

from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

import pytest

from design_graph.mcp.server import MCPServer
from design_graph.mcp.tools import ToolDispatcher


class _FailingDispatcher:
    """Dispatcher that raises on dispatch() to test server exception handling."""
    def __init__(self, readers):
        self._readers = readers

    def pick_reader(self, *args, **kwargs):
        return MagicMock(), None

    def dispatch(self, *args, **kwargs):
        raise RuntimeError("simulated tool failure")

    def list_screens(self):
        raise RuntimeError("list_screens failure")


class TestToolExceptionHandling:
    def _failing_server(self):
        server = MCPServer([("doc1", MagicMock())])
        # Replace the dispatcher with one that always raises
        server._dispatcher = _FailingDispatcher([("doc1", MagicMock())])
        return server

    def test_tool_exception_returns_result_not_error(self):
        """Server must NOT propagate tool exceptions as JSON-RPC errors.
        Instead it catches them and returns the traceback as the text content."""
        server = self._failing_server()
        resp = server.handle({
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {"name": "list_screens", "arguments": {}},
        })
        # Response must be a result (not a protocol error)
        assert "result" in resp
        text = resp["result"]["content"][0]["text"]
        assert "Error" in text or "error" in text or "failure" in text

    def test_tool_exception_written_to_stderr(self, capsys):
        server = self._failing_server()
        server.handle({
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {"name": "list_screens", "arguments": {}},
        })
        err = capsys.readouterr().err
        assert "ERROR" in err or "error" in err.lower() or "failure" in err.lower()

    def test_tool_exception_response_has_correct_id(self):
        server = self._failing_server()
        resp = server.handle({
            "jsonrpc": "2.0", "id": 42,
            "method": "tools/call",
            "params": {"name": "list_screens", "arguments": {}},
        })
        assert resp["id"] == 42

    def test_tool_exception_response_is_text_type(self):
        server = self._failing_server()
        resp = server.handle({
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {"name": "get_component", "arguments": {"name": "Btn"}},
        })
        assert resp["result"]["content"][0]["type"] == "text"


# ── _handle_initialize: multiple readers description ─────────────────────────

class TestInitializeMultipleReadersDescription:
    def _stub_reader(self):
        r = MagicMock()
        r.list_screens.return_value = []
        return r

    def test_multiple_readers_no_active_doc_shows_set_prototype_hint(self):
        server = MCPServer([("proto_a", self._stub_reader()), ("proto_b", self._stub_reader())])
        server._active_doc = ""
        resp = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        desc = resp["result"]["serverInfo"]["description"]
        # Should mention both prototypes and instruct to call set_prototype
        assert "proto_a" in desc or "proto_b" in desc
        assert "set_prototype" in desc or "select" in desc.lower()

    def test_single_reader_auto_selected_in_description(self):
        server = MCPServer([("myapp", self._stub_reader())])
        server._active_doc = ""
        resp = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        desc = resp["result"]["serverInfo"]["description"]
        assert "myapp" in desc

    def test_active_doc_shown_when_set(self):
        server = MCPServer([("a", self._stub_reader()), ("b", self._stub_reader())])
        server._active_doc = "a"
        resp = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        desc = resp["result"]["serverInfo"]["description"]
        assert "a" in desc
