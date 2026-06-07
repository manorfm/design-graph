"""
TDD — Etapa 1 (MCP): get_screen_layout tool tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from design_graph.graph.reader import GraphReader
from design_graph.mcp.tools import ToolDispatcher


@pytest.fixture
def reader_with_layout():
    reader = MagicMock(spec=GraphReader)
    reader.get_screen_layout.return_value = [
        {
            "component_name": "NavBar",
            "display": "flex",
            "position": None,
            "width": "100%",
            "height": "64px",
            "padding": None,
            "padding_top": None,
            "padding_right": None,
            "padding_bottom": None,
            "padding_left": None,
            "margin": None,
            "margin_top": None,
            "margin_right": None,
            "margin_bottom": None,
            "margin_left": None,
            "flex_direction": "row",
            "align_items": "center",
            "justify_content": "space-between",
            "gap": None,
            "overflow": None,
            "z_index": "10",
            "extra_layout": {},
        },
        {
            "component_name": "ContentGrid",
            "display": "grid",
            "position": None,
            "width": None,
            "height": None,
            "padding": "16px",
            "padding_top": None,
            "padding_right": None,
            "padding_bottom": None,
            "padding_left": None,
            "margin": None,
            "margin_top": None,
            "margin_right": None,
            "margin_bottom": None,
            "margin_left": None,
            "flex_direction": None,
            "align_items": None,
            "justify_content": None,
            "gap": "12px",
            "overflow": None,
            "z_index": None,
            "extra_layout": {"gridTemplateColumns": "repeat(3,1fr)"},
        },
    ]
    return reader


@pytest.fixture
def dispatcher(reader_with_layout):
    return ToolDispatcher([("myapp", reader_with_layout)])


class TestGetScreenLayoutTool:
    def test_tool_exists_in_tool_definitions(self):
        from design_graph.mcp.tools import TOOL_DEFINITIONS
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "get_screen_layout" in names

    def test_requires_name_parameter(self):
        from design_graph.mcp.tools import TOOL_DEFINITIONS
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "get_screen_layout")
        assert "name" in tool["inputSchema"]["required"]

    def test_dispatches_to_reader_get_screen_layout(self, dispatcher, reader_with_layout):
        dispatcher.dispatch("get_screen_layout", {"name": "DashboardPage"}, "myapp")
        reader_with_layout.get_screen_layout.assert_called_once_with("DashboardPage")

    def test_output_contains_component_names(self, dispatcher):
        output = dispatcher.dispatch("get_screen_layout", {"name": "DashboardPage"}, "myapp")
        assert "NavBar" in output
        assert "ContentGrid" in output

    def test_output_contains_display_value(self, dispatcher):
        output = dispatcher.dispatch("get_screen_layout", {"name": "DashboardPage"}, "myapp")
        assert "flex" in output
        assert "grid" in output

    def test_output_contains_dimensions(self, dispatcher):
        output = dispatcher.dispatch("get_screen_layout", {"name": "DashboardPage"}, "myapp")
        assert "100%" in output
        assert "64px" in output

    def test_output_contains_extra_layout(self, dispatcher):
        output = dispatcher.dispatch("get_screen_layout", {"name": "DashboardPage"}, "myapp")
        assert "gridTemplateColumns" in output

    def test_returns_not_found_message_when_reader_returns_empty(self, dispatcher, reader_with_layout):
        reader_with_layout.get_screen_layout.return_value = []
        output = dispatcher.dispatch("get_screen_layout", {"name": "NoScreen"}, "myapp")
        assert "not found" in output.lower() or "não encontrada" in output.lower()

    def test_unknown_tool_name_is_not_affected(self, dispatcher):
        output = dispatcher.dispatch("get_screen_layout", {"name": "x"}, "myapp")
        assert "Unknown tool" not in output
