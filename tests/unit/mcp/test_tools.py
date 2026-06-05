"""Tests for mcp/tools.py and mcp/server.py — T15."""

import pytest

from design_graph.mcp.server import MCPServer
from design_graph.mcp.tools import TOOL_DEFINITIONS, ToolDispatcher


# ── Mock reader ───────────────────────────────────────────────────────────────

class MockReader:
    """Minimal GraphReader stub for MCP unit tests."""

    def list_screens(self):
        return [{"name": "RestaurantsPage", "component_count": 3,
                 "sections_count": 2, "top_components": ["SectionCard", "BtnPrimary"]}]

    def get_screen(self, name):
        if "Restaurants" in name:
            return {"name": "RestaurantsPage", "component_count": 3,
                    "sections_count": 2, "components": [], "sections": [], "texts": []}
        return None

    def get_component(self, name):
        return {"c.name": name, "c.comp_type": "card", "c.jsx_snippet": "<div/>",
                "c.occurrence": 2, "c.classes": "card",
                "styles": [], "tokens": [], "texts": [], "interactions": [],
                "screens_using": ["RestaurantsPage"], "children": []}

    def get_component_children(self, name):
        if name == "BtnWithBadge":
            return ["Badge"]
        return []

    def get_tokens(self, category=None):
        return [{"t.label": "primary", "t.value": "#ffb81c",
                 "t.category": "color", "t.id": "col_1", "t.usage": 5}]

    def get_interactions(self, name): return []
    def get_full_jsx(self, name): return "<div>full jsx</div>"
    def get_impact(self, name):
        return {"found": True, "type": "card", "screens": ["RestaurantsPage"],
                "sections": [], "tokens_used": []}
    def find_token_usage(self, value): return []
    def get_section(self, screen, section): return None
    def count_nodes(self): return {}
    def find_screens_using_comp_transitively(self, name): return []
    def get_component_parents(self, name): return []


def _dispatcher(n=2):
    readers = [(f"doc{i}", MockReader()) for i in range(1, n + 1)]
    return ToolDispatcher(readers)


# ── ToolDispatcher.pick_reader tests ─────────────────────────────────────────

class TestPickReader:
    def test_explicit_doc_wins(self):
        d = _dispatcher(2)
        reader, err = d.pick_reader(doc="doc1", active_doc="doc2")
        assert reader is not None
        assert err is None

    def test_active_doc_used_when_no_explicit(self):
        d = _dispatcher(2)
        reader, err = d.pick_reader(doc=None, active_doc="doc2")
        assert reader is not None
        assert err is None

    def test_auto_select_when_single_reader(self):
        d = ToolDispatcher([("only", MockReader())])
        reader, err = d.pick_reader(doc=None, active_doc="")
        assert reader is not None
        assert err is None

    def test_error_multiple_no_selection(self):
        d = _dispatcher(2)
        reader, err = d.pick_reader(doc=None, active_doc="")
        assert reader is None
        assert err is not None
        assert "set_prototype" in err or "doc=" in err

    def test_error_unknown_doc(self):
        d = _dispatcher(2)
        reader, err = d.pick_reader(doc="ghost", active_doc="")
        assert reader is None
        assert "ghost" in err.lower() or "not found" in err.lower()

    def test_error_no_readers(self):
        d = ToolDispatcher([])
        reader, err = d.pick_reader(doc=None, active_doc="")
        assert reader is None
        assert err is not None


class TestDispatch:
    def test_list_screens_returns_markdown(self):
        d = ToolDispatcher([("doc1", MockReader())])
        result = d.dispatch("list_screens", {}, "")
        assert isinstance(result, str)
        assert "RestaurantsPage" in result

    def test_unknown_tool_returns_error(self):
        d = ToolDispatcher([("doc1", MockReader())])
        result = d.dispatch("nonexistent_tool", {}, "doc1")
        assert "unknown" in result.lower() or "nonexistent" in result.lower()

    def test_get_component_children_returns_markdown(self):
        d = ToolDispatcher([("doc1", MockReader())])
        result = d.dispatch("get_component_children", {"name": "BtnWithBadge"}, "doc1")
        assert "Badge" in result

    def test_search_cross_prototype(self):
        d = _dispatcher(2)
        result = d.dispatch("search", {"query": "primary"}, "")
        assert isinstance(result, str)


class TestToolDefinitions:
    def test_all_standard_tools_defined(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        expected = {
            "list_screens", "get_screen", "get_section", "get_component",
            "get_tokens", "find_token_usage", "search", "impact",
            "get_full_jsx", "get_component_interactions",
            "get_component_children",
            "set_prototype",
        }
        assert expected.issubset(names)

    def test_each_tool_has_meaningful_description(self):
        for tool in TOOL_DEFINITIONS:
            assert len(tool.get("description", "")) > 20, f"{tool['name']} has short description"

    def test_each_tool_has_object_input_schema(self):
        for tool in TOOL_DEFINITIONS:
            assert tool.get("inputSchema", {}).get("type") == "object"


# ── MCPServer tests ───────────────────────────────────────────────────────────

class TestMCPServer:
    def _server(self, n=1):
        readers = [(f"doc{i}", MockReader()) for i in range(1, n + 1)]
        return MCPServer(readers)

    def _msg(self, method, params=None, mid=1):
        return {"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}

    def test_initialize_returns_protocol_version(self):
        response = self._server().handle(self._msg("initialize"))
        assert response["result"]["protocolVersion"] == "2024-11-05"

    def test_tools_list_includes_new_tool(self):
        response = self._server().handle(self._msg("tools/list"))
        names = [t["name"] for t in response["result"]["tools"]]
        assert "get_component_children" in names

    def test_tools_call_list_screens(self):
        response = self._server().handle(self._msg("tools/call", {
            "name": "list_screens", "arguments": {}
        }))
        assert response["result"]["content"][0]["type"] == "text"
        assert "RestaurantsPage" in response["result"]["content"][0]["text"]

    def test_unknown_method_returns_error_32601(self):
        response = self._server().handle(self._msg("nonexistent"))
        assert response["error"]["code"] == -32601

    def test_notification_returns_none(self):
        result = self._server().handle(self._msg("notifications/initialized"))
        assert result is None

    def test_set_prototype_updates_active_doc(self):
        server = self._server(2)
        server.handle(self._msg("tools/call", {
            "name": "set_prototype", "arguments": {"name": "doc2"}
        }))
        assert server._active_doc == "doc2"

    def test_set_prototype_no_arg_reports_state(self):
        server = self._server(1)
        response = server.handle(self._msg("tools/call", {
            "name": "set_prototype", "arguments": {}
        }))
        text = response["result"]["content"][0]["text"]
        assert isinstance(text, str)
        assert len(text) > 0
