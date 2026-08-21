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

    def get_tokens(self, category=None, screen=None):
        return [{"t.label": "primary", "t.value": "#ffb81c",
                 "t.category": "color", "t.id": "col_1", "t.usage": 5}]

    def list_texts(self):
        return []

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

    def list_components(self, comp_type=None):
        comps = [
            {"c.name": "BtnPrimary", "c.comp_type": "button", "c.occurrence": 5},
            {"c.name": "CartItem",   "c.comp_type": "card",   "c.occurrence": 2},
        ]
        if comp_type:
            return [c for c in comps if c["c.comp_type"] == comp_type]
        return comps

    def get_component_spec(self, name):
        if "Ghost" in name or "Nonexistent" in name:
            return None
        return {
            "c.name": name, "c.comp_type": "button",
            "c.jsx_snippet": "<button/>", "c.occurrence": 5, "c.classes": "",
            "styles_by_state": {"default": [{"property": "color", "value": "red"}]},
            "tokens": [], "texts": [], "interactions": [],
            "children": [], "parents": [], "screens_using": ["RestaurantsPage"],
        }


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


class _WeakMatchOnlyReader:
    """
    A single UIText sharing only one of a two-word query's words with the
    text — no result anywhere covers the full query. Reproduces
    search("Destinos operacionais") returning "Alertas operacionais" with
    nothing in the rendered output to say it's a partial, not exact, hit.
    """

    def list_screens(self): return []
    def list_components(self, comp_type=None): return []
    def get_tokens(self, category=None): return []
    def list_texts(self):
        return [{"t.id": "t1", "t.content": "Alertas operacionais", "t.source": "InventoryOverview"}]


class TestSearchWeakMatchWarning:
    def test_partial_only_results_carry_an_explicit_warning(self):
        d = ToolDispatcher([("doc1", _WeakMatchOnlyReader())])
        result = d.dispatch("search", {"query": "Destinos operacionais"}, "doc1")
        assert "Alertas operacionais" in result
        assert "parcial" in result.lower()

    def test_full_match_carries_no_partial_warning(self):
        d = ToolDispatcher([("doc1", MockReader())])
        result = d.dispatch("search", {"query": "RestaurantsPage"}, "doc1")
        assert "parcial" not in result.lower()


class TestListComponentsTool:
    def test_tool_in_definitions(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "list_components" in names

    def test_tool_has_meaningful_description(self):
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "list_components")
        assert len(tool["description"]) > 20

    def test_dispatch_no_filter_returns_markdown_table(self):
        result = _dispatcher(1).dispatch("list_components", {}, "doc1")
        assert isinstance(result, str)
        assert "|" in result

    def test_dispatch_with_type_filter_returns_filtered(self):
        result = _dispatcher(1).dispatch("list_components", {"comp_type": "button"}, "doc1")
        assert isinstance(result, str)
        assert "button" in result.lower()

    def test_dispatch_unknown_type_returns_no_results_message(self):
        result = _dispatcher(1).dispatch("list_components", {"comp_type": "xyz_unknown"}, "doc1")
        assert isinstance(result, str)


class TestGetComponentSpecTool:
    def test_tool_in_definitions(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "get_component_spec" in names

    def test_tool_requires_name_in_schema(self):
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "get_component_spec")
        assert "name" in tool["inputSchema"].get("required", [])

    def test_dispatch_known_component_returns_markdown(self):
        result = _dispatcher(1).dispatch("get_component_spec", {"name": "BtnPrimary"}, "doc1")
        assert isinstance(result, str)
        assert "BtnPrimary" in result

    def test_dispatch_unknown_returns_not_found_message(self):
        result = _dispatcher(1).dispatch("get_component_spec", {"name": "GhostComp"}, "doc1")
        assert "not found" in result.lower() or "ghostcomp" in result.lower()

    def test_output_contains_style_section(self):
        result = _dispatcher(1).dispatch("get_component_spec", {"name": "BtnPrimary"}, "doc1")
        assert "default" in result.lower() or "estilo" in result.lower() or "style" in result.lower()


class TestToolDefinitions:
    def test_all_standard_tools_defined(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        expected = {
            "list_screens", "get_screen", "get_section", "get_component",
            "get_tokens", "find_token_usage", "search", "impact",
            "get_full_jsx", "get_component_interactions",
            "get_component_children", "list_components", "get_component_spec",
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
#
# MCPServer itself no longer speaks JSON-RPC — that's the mcp SDK's job now
# (wired at the bottom of server.py). These tests exercise MCPServer's own
# responsibility: tool definitions, dispatch, session state and reload —
# all through plain dicts/strings, with no SDK types involved.

class TestMCPServer:
    def _server(self, n=1):
        readers = [(f"doc{i}", MockReader()) for i in range(1, n + 1)]
        return MCPServer(readers)

    def test_tool_definitions_includes_new_tool(self):
        names = [t["name"] for t in self._server().tool_definitions()]
        assert "get_component_children" in names

    def test_dispatch_list_screens(self):
        result = self._server().dispatch_tool_call("list_screens", {})
        assert result.is_error is False
        assert "RestaurantsPage" in result.text

    def test_dispatch_unknown_tool_is_not_an_error(self):
        """An unrecognized tool name is a routing miss, not an execution
        failure — ToolDispatcher already reports it as text."""
        result = self._server().dispatch_tool_call("nonexistent", {})
        assert result.is_error is False
        assert "unknown" in result.text.lower() or "nonexistent" in result.text.lower()

    def test_set_prototype_updates_active_doc(self):
        server = self._server(2)
        server.dispatch_tool_call("set_prototype", {"name": "doc2"})
        assert server._active_doc == "doc2"

    def test_set_prototype_no_arg_reports_state(self):
        server = self._server(1)
        result = server.dispatch_tool_call("set_prototype", {})
        assert isinstance(result.text, str)
        assert result.is_error is False
