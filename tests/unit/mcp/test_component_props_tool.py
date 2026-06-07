"""
TDD — Etapa 5c: get_component_props MCP tool.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from design_graph.graph.reader import GraphReader
from design_graph.mcp.tools import TOOL_DEFINITIONS, ToolDispatcher


@pytest.fixture
def reader_with_props():
    reader = MagicMock(spec=GraphReader)
    reader.get_component_props.return_value = [
        {"prop_name": "title",   "default_value": "",        "component_name": "NavBar"},
        {"prop_name": "sticky",  "default_value": "false",   "component_name": "NavBar"},
        {"prop_name": "onClose", "default_value": "",        "component_name": "NavBar"},
    ]
    return reader


@pytest.fixture
def dispatcher(reader_with_props):
    return ToolDispatcher([("myapp", reader_with_props)])


class TestGetComponentPropsTool:
    def test_tool_definition_exists(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "get_component_props" in names

    def test_tool_requires_name_parameter(self):
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "get_component_props")
        assert "name" in tool["inputSchema"]["required"]

    def test_dispatch_calls_reader_get_component_props(self, dispatcher, reader_with_props):
        dispatcher.dispatch("get_component_props", {"name": "NavBar"}, "myapp")
        reader_with_props.get_component_props.assert_called_once_with("NavBar")

    def test_output_lists_all_prop_names(self, dispatcher):
        output = dispatcher.dispatch("get_component_props", {"name": "NavBar"}, "myapp")
        assert "title" in output
        assert "sticky" in output
        assert "onClose" in output

    def test_output_marks_required_props(self, dispatcher):
        output = dispatcher.dispatch("get_component_props", {"name": "NavBar"}, "myapp")
        assert "required" in output.lower()

    def test_output_shows_default_value_for_optional_props(self, dispatcher):
        output = dispatcher.dispatch("get_component_props", {"name": "NavBar"}, "myapp")
        assert "false" in output  # sticky default

    def test_not_found_returns_informative_message(self, dispatcher, reader_with_props):
        reader_with_props.get_component_props.return_value = []
        output = dispatcher.dispatch("get_component_props", {"name": "Unknown"}, "myapp")
        assert "not found" in output.lower() or "sem props" in output.lower() or "no props" in output.lower()
