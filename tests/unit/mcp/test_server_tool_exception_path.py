"""
Tests for MCPServer's tool-exception path and multi-reader startup text.

Targets:
  - dispatch_tool_call's except block: a tool that raises must come back as
    ToolCallResult(is_error=True) with a plain message — not a leaked
    traceback in the text a client/LLM would see. The full traceback still
    goes to stderr for whoever operates the process.
  - startup_description() with multiple readers and no active_doc.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from design_graph.mcp.server import MCPServer


class _FailingDispatcher:
    """Dispatcher that raises on dispatch() to test server exception handling."""
    def __init__(self, readers):
        self._readers = readers

    def pick_reader(self, *args, **kwargs):
        return MagicMock(), None

    def dispatch(self, *args, **kwargs):
        raise RuntimeError("simulated tool failure")


class TestToolExceptionHandling:
    def _failing_server(self):
        server = MCPServer([("doc1", MagicMock())])
        server._dispatcher = _FailingDispatcher([("doc1", MagicMock())])
        return server

    def test_tool_exception_is_reported_as_an_error(self):
        result = self._failing_server().dispatch_tool_call("list_screens", {})
        assert result.is_error is True
        assert "failure" in result.text.lower() or "error" in result.text.lower()

    def test_tool_exception_text_does_not_leak_a_traceback(self):
        """The client sees a message, not a stack trace — full detail stays
        server-side, in stderr."""
        result = self._failing_server().dispatch_tool_call("list_screens", {})
        assert "Traceback" not in result.text

    def test_tool_exception_written_to_stderr(self, capsys):
        self._failing_server().dispatch_tool_call("list_screens", {})
        err = capsys.readouterr().err
        assert "error" in err.lower() or "failure" in err.lower()


# ── startup_description: multiple readers ────────────────────────────────────

class TestStartupDescriptionMultipleReaders:
    def _stub_reader(self):
        r = MagicMock()
        r.list_screens.return_value = []
        return r

    def test_multiple_readers_no_active_doc_shows_set_prototype_hint(self):
        server = MCPServer([("proto_a", self._stub_reader()), ("proto_b", self._stub_reader())])
        server._active_doc = ""
        desc = server.startup_description()
        assert "proto_a" in desc or "proto_b" in desc
        assert "set_prototype" in desc or "select" in desc.lower()

    def test_single_reader_auto_selected_in_description(self):
        server = MCPServer([("myapp", self._stub_reader())])
        server._active_doc = ""
        assert "myapp" in server.startup_description()

    def test_active_doc_shown_when_set(self):
        server = MCPServer([("a", self._stub_reader()), ("b", self._stub_reader())])
        server._active_doc = "a"
        assert "a" in server.startup_description()
