"""
Tests for MCPServer's call-metrics instrumentation: dispatch_tool_call must
record one CallRecord per call (including set_prototype) via mcp/metrics.py,
classify its outcome, and never let a metrics-writing failure change the
ToolCallResult the client actually sees.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from design_graph.mcp.server import MCPServer


class _StubDispatcher:
    """Dispatcher stub whose dispatch() either returns fixed text or raises."""

    def __init__(self, readers, text="ok", raises=None):
        self._readers = readers
        self._text = text
        self._raises = raises

    def pick_reader(self, *args, **kwargs):
        return MagicMock(), None

    def dispatch(self, *args, **kwargs):
        if self._raises:
            raise self._raises
        return self._text


def _server_with(text="ok", raises=None, active_doc=""):
    server = MCPServer([("doc1", MagicMock())])
    server._dispatcher = _StubDispatcher([("doc1", MagicMock())], text=text, raises=raises)
    server._active_doc = active_doc
    return server


def _capture(monkeypatch):
    captured = []
    monkeypatch.setattr("design_graph.mcp.metrics.record_call", lambda record: captured.append(record))
    return captured


class TestMetricsRecordedPerCall:
    def test_ok_call_is_recorded_with_ok_outcome(self, monkeypatch):
        captured = _capture(monkeypatch)
        server = _server_with(text="# Spec: BtnPrimary", active_doc="toToggle")

        server.dispatch_tool_call("get_component", {"name": "BtnPrimary"})

        assert len(captured) == 1
        record = captured[0]
        assert record.tool == "get_component"
        assert record.prototype == "toToggle"
        assert record.outcome == "ok"
        assert record.duration_ms >= 0
        assert record.response_chars == len("# Spec: BtnPrimary")
        assert record.arguments == {"name": "BtnPrimary"}

    def test_not_found_text_is_classified(self, monkeypatch):
        captured = _capture(monkeypatch)
        server = _server_with(text="Componente 'X' não encontrado. Use search('X').")

        server.dispatch_tool_call("get_component", {"name": "X"})

        assert captured[0].outcome == "not_found"

    def test_raised_exception_is_classified_as_error(self, monkeypatch):
        captured = _capture(monkeypatch)
        server = _server_with(raises=RuntimeError("boom"))

        server.dispatch_tool_call("get_component", {"name": "X"})

        assert captured[0].outcome == "error"

    def test_set_prototype_is_also_recorded(self, monkeypatch):
        captured = _capture(monkeypatch)
        server = _server_with()

        server.dispatch_tool_call("set_prototype", {"name": "doc1"})

        assert len(captured) == 1
        assert captured[0].tool == "set_prototype"

    def test_explicit_doc_argument_wins_over_active_doc(self, monkeypatch):
        captured = _capture(monkeypatch)
        server = _server_with(active_doc="toToggle")

        server.dispatch_tool_call("get_component", {"name": "X", "doc": "ipede-v7"})

        assert captured[0].prototype == "ipede-v7"

    def test_no_doc_anywhere_records_none_prototype(self, monkeypatch):
        captured = _capture(monkeypatch)
        server = _server_with(active_doc="")

        server.dispatch_tool_call("search", {"query": "x"})

        assert captured[0].prototype is None


class TestMetricsWriteFailureNeverBreaksToolCallResult:
    def test_recording_exception_does_not_change_result(self, monkeypatch):
        def _boom(record):
            raise RuntimeError("disk full")

        monkeypatch.setattr("design_graph.mcp.metrics.record_call", _boom)
        server = _server_with(text="fine")

        result = server.dispatch_tool_call("get_component", {"name": "X"})

        assert result.text == "fine"
        assert result.is_error is False

    def test_recording_exception_does_not_change_error_result(self, monkeypatch):
        def _boom(record):
            raise RuntimeError("disk full")

        monkeypatch.setattr("design_graph.mcp.metrics.record_call", _boom)
        server = _server_with(raises=RuntimeError("real tool failure"))

        result = server.dispatch_tool_call("get_component", {"name": "X"})

        assert result.is_error is True
        assert "Traceback" not in result.text


class TestMetricsDisabledEnvVar:
    def test_disabled_env_var_suppresses_recording(self, monkeypatch):
        monkeypatch.setenv("DESIGN_GRAPH_METRICS_DISABLED", "1")
        captured = _capture(monkeypatch)
        server = _server_with()

        server.dispatch_tool_call("get_component", {"name": "X"})

        assert captured == []

    def test_not_set_records_normally(self, monkeypatch):
        monkeypatch.delenv("DESIGN_GRAPH_METRICS_DISABLED", raising=False)
        captured = _capture(monkeypatch)
        server = _server_with()

        server.dispatch_tool_call("get_component", {"name": "X"})

        assert len(captured) == 1
