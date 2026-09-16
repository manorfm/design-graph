"""Shared pytest fixtures and helpers for the design-graph test suite."""

import pytest


@pytest.fixture(autouse=True)
def _isolate_metrics_log(tmp_path, monkeypatch):
    """
    MCPServer.dispatch_tool_call now writes one metrics line per call
    (mcp/metrics.py) at its default path. Without this, any test that
    builds a real MCPServer/ToolDispatcher and calls dispatch_tool_call —
    several already did, before metrics existed — would silently pollute
    the real user's ~/.local/share/design-graph/metrics.jsonl with test
    fixture data every time the suite runs. Redirect metrics_path() to a
    per-test tmp file so no test ever touches real user state, whether or
    not it exercises metrics directly.
    """
    fake_path = tmp_path / "metrics.jsonl"
    monkeypatch.setattr("design_graph.mcp.metrics.metrics_path", lambda: fake_path)
