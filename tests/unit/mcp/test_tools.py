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

    def component_exists(self, name):
        return name in ("BtnWithBadge", "SectionCard")

    def get_tokens(self, category=None, screen=None):
        return [{"t.label": "primary", "t.value": "#ffb81c",
                 "t.category": "color", "t.id": "col_1", "t.usage": 5}]

    def list_texts(self):
        return []

    def list_shared_style_classes(self):
        return []

    def get_interactions(self, name): return []
    def get_full_jsx(self, name): return "<div>full jsx</div>"
    def get_impact(self, name):
        return {"found": True, "type": "card", "screens": ["RestaurantsPage"],
                "sections": [], "tokens_used": []}
    def find_token_usage(self, value): return []
    def get_section(self, screen, section):
        if section == "Ghost":
            return None
        return {
            "id": "sec1", "name": "Header", "detection_method": "comment",
            "styles_by_element": {
                ".audit-item": [{"property": f"prop{i}", "value": f"val{i}"} for i in range(10)],
                ".audit-dot": [{"property": "display", "value": "flex"}],
            },
            "component_refs": [], "texts": [], "jsx_snippet": "",
        }
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
        if "Ghost" in name or "Nonexistent" in name or name == "page-title":
            return None
        if name == "ManyStylesComp":
            return {
                "c.name": name, "c.comp_type": "card",
                "c.jsx_snippet": "<div/>", "c.occurrence": 1, "c.classes": "",
                "styles_by_state": {
                    "default": [{"property": f"prop{i}", "value": f"val{i}"} for i in range(15)],
                },
                "tokens": [], "texts": [], "interactions": [],
                "children": [], "parents": [], "screens_using": [],
            }
        return {
            "c.name": name, "c.comp_type": "button",
            "c.jsx_snippet": "<button/>", "c.occurrence": 5, "c.classes": "",
            "styles_by_state": {"default": [{"property": "color", "value": "red"}]},
            "tokens": [], "texts": [], "interactions": [],
            "children": [], "parents": [], "screens_using": ["RestaurantsPage"],
        }

    def find_styles_by_class(self, class_name):
        if class_name == "page-title":
            return [
                {"property": "font-size", "value": "25px"},
                {"property": "font-weight", "value": "600"},
            ]
        return []

    def find_class_owners(self, class_name):
        if class_name == "page-title":
            return {"components": [], "sections": [{"screen": "Applications", "section": "Header"}]}
        return {"components": [], "sections": []}

    def get_component_full(self, name):
        if "Ghost" in name or "Nonexistent" in name:
            return None
        return {
            "root": name,
            "components": [
                {
                    "name": name, "comp_type": "card", "jsx_snippet": "<div/>",
                    "occurrence": 2, "classes": "", "truncated_fields": [],
                    "styles_by_state": {"default": [{"property": "display", "value": "flex"}]},
                    "tokens": [], "texts": [], "interactions": [], "props": [],
                    "children": ["Badge"],
                },
                {
                    "name": "Badge", "comp_type": "badge", "jsx_snippet": "<span/>",
                    "occurrence": 1, "classes": "", "truncated_fields": [],
                    "styles_by_state": {}, "tokens": [], "texts": [],
                    "interactions": [], "props": [], "children": [],
                },
            ],
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

    def test_get_component_children_leaf_component_message(self):
        # Exists (component_exists=True) but has no children — distinct
        # message from "not found" (C27/T53).
        d = ToolDispatcher([("doc1", MockReader())])
        result = d.dispatch("get_component_children", {"name": "SectionCard"}, "doc1")
        assert "folha" in result
        assert "não encontrado" not in result

    def test_get_component_children_not_found_message(self):
        d = ToolDispatcher([("doc1", MockReader())])
        result = d.dispatch("get_component_children", {"name": "TotallyUnknown"}, "doc1")
        assert "não encontrado" in result
        assert "folha" not in result

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

    def list_shared_style_classes(self): return []


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


class TestGetComponentSpecFallsBackToSharedCssClass:
    """
    A CSS class reused across screens but never factored into a named React
    component (e.g. `.page-title`) used to be a dead end: get_component_spec
    said "not found" with no other avenue. When normal component resolution
    finds nothing, falling back to find_styles_by_class surfaces the same
    facts a real component spec would (styles, "used in") — clearly labeled
    as a CSS class, not a component (see docs/changes/C36 P3).
    """

    def test_falls_back_to_shared_class_when_no_component_matches(self):
        result = _dispatcher(1).dispatch("get_component_spec", {"name": "page-title"}, "doc1")
        assert "font-size" in result
        assert "25px" in result

    def test_labeled_as_css_class_not_component(self):
        result = _dispatcher(1).dispatch("get_component_spec", {"name": "page-title"}, "doc1")
        assert "classe css" in result.lower() or "css class" in result.lower()

    def test_reports_screen_using_the_class(self):
        result = _dispatcher(1).dispatch("get_component_spec", {"name": "page-title"}, "doc1")
        assert "Applications" in result

    def test_real_component_match_never_falls_back(self):
        """A genuine component hit must win outright — the class fallback
        only runs when component resolution finds literally nothing."""
        result = _dispatcher(1).dispatch("get_component_spec", {"name": "BtnPrimary"}, "doc1")
        assert "classe css" not in result.lower()

    def test_unknown_name_that_is_also_not_a_class_stays_not_found(self):
        result = _dispatcher(1).dispatch("get_component_spec", {"name": "GhostComp"}, "doc1")
        assert "not found" in result.lower() or "ghostcomp" in result.lower()


class TestGetFullStylesTool:
    """
    get_full_jsx has no style equivalent — get_section/get_screen_full/
    get_component_spec all truncate their style tables (`+N mais`) with no
    way to recover what was cut. get_full_styles renders the reader's
    already-complete data (the cap is a display-layer slice, not a query
    limit) without slicing it (see docs/changes/C36).
    """

    def test_tool_in_definitions(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "get_full_styles" in names

    def test_section_styles_are_not_truncated(self):
        result = _dispatcher(1).dispatch(
            "get_full_styles", {"screen": "HistoryView", "section": "Header"}, "doc1",
        )
        assert "prop9" in result  # 10th entry — beyond any display cap
        assert "mais" not in result.lower()

    def test_section_styles_grouped_by_selector(self):
        result = _dispatcher(1).dispatch(
            "get_full_styles", {"screen": "HistoryView", "section": "Header"}, "doc1",
        )
        assert ".audit-item" in result
        assert ".audit-dot" in result

    def test_unknown_section_returns_not_found_message(self):
        result = _dispatcher(1).dispatch(
            "get_full_styles", {"screen": "HistoryView", "section": "Ghost"}, "doc1",
        )
        assert "não encontrada" in result.lower() or "not found" in result.lower()

    def test_component_styles_are_not_truncated(self):
        result = _dispatcher(1).dispatch("get_full_styles", {"name": "ManyStylesComp"}, "doc1")
        assert "prop14" in result  # 15th entry — beyond the 12-item display cap
        assert "mais" not in result.lower()

    def test_falls_back_to_shared_css_class_when_no_component_matches(self):
        """
        get_component_spec("page-title") falls back to find_styles_by_class
        when no component matches — get_full_styles(name="page-title") must
        do the same, or a class-only lookup silently works through one tool
        and not its "full" counterpart (reported gap, docs/changes/C37).
        """
        result = _dispatcher(1).dispatch("get_full_styles", {"name": "page-title"}, "doc1")
        assert "font-size" in result
        assert "25px" in result

    def test_unknown_component_returns_not_found_message(self):
        result = _dispatcher(1).dispatch("get_full_styles", {"name": "GhostComp"}, "doc1")
        assert "não encontrado" in result.lower() or "not found" in result.lower()

    def test_neither_name_nor_screen_section_given(self):
        result = _dispatcher(1).dispatch("get_full_styles", {}, "doc1")
        assert "name" in result.lower() or "screen" in result.lower()


class TestGetComponentFullTool:
    def test_tool_in_definitions(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "get_component_full" in names

    def test_tool_requires_name_in_schema(self):
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "get_component_full")
        assert "name" in tool["inputSchema"].get("required", [])

    def test_dispatch_known_component_returns_markdown_with_descendants(self):
        result = _dispatcher(1).dispatch("get_component_full", {"name": "BtnPrimary"}, "doc1")
        assert isinstance(result, str)
        assert "BtnPrimary" in result
        assert "Badge" in result  # descendant included, not just the root

    def test_dispatch_unknown_returns_not_found_message(self):
        result = _dispatcher(1).dispatch("get_component_full", {"name": "GhostComp"}, "doc1")
        assert "não encontrado" in result.lower() or "ghostcomp" in result.lower()

    def test_root_marked_in_output(self):
        result = _dispatcher(1).dispatch("get_component_full", {"name": "BtnPrimary"}, "doc1")
        assert "(raiz)" in result


class TestExtractValidationCandidate:
    def test_wraps_bare_jsx_and_extracts_inline_style(self):
        from design_graph.mcp.tools import _extract_validation_candidate
        candidate = _extract_validation_candidate('<button style={{color: "red"}}>OK</button>')
        assert candidate is not None
        assert any(s.property == "color" and s.value == "red" for s in candidate.styles)

    def test_captures_child_refs(self):
        from design_graph.mcp.tools import _extract_validation_candidate
        candidate = _extract_validation_candidate("<div><Sparkline /><Badge /></div>")
        assert candidate is not None
        assert set(candidate.child_refs) == {"Sparkline", "Badge"}

    def test_spread_reference_is_not_resolved_without_whole_file_context(self):
        # Documented limitation (C33 spike finding): a spread referencing a
        # shared style object can't resolve for an isolated snippet — no
        # "rest of the file" to search for the const declaration.
        from design_graph.mcp.tools import _extract_validation_candidate
        candidate = _extract_validation_candidate('<div style={{...sharedStyle, width: 34}} />')
        assert candidate is not None
        props = {s.property for s in candidate.styles}
        assert "width" in props
        # sharedStyle's own properties are simply absent, not wrong — this
        # is exactly the documented gap, not a crash or false data.


class TestValidateComponentImplementationTool:
    def test_tool_in_definitions(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "validate_component_implementation" in names

    def test_tool_requires_name_and_jsx_source(self):
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "validate_component_implementation")
        required = tool["inputSchema"].get("required", [])
        assert "name" in required and "jsx_source" in required

    def test_empty_jsx_source_reports_nothing_to_compare(self):
        result = _dispatcher(1).dispatch(
            "validate_component_implementation", {"name": "BtnPrimary", "jsx_source": ""}, "doc1",
        )
        assert "vazio" in result.lower()

    def test_unknown_component_reports_not_found(self):
        result = _dispatcher(1).dispatch(
            "validate_component_implementation",
            {"name": "GhostComp", "jsx_source": "<div/>"}, "doc1",
        )
        assert "não encontrado" in result.lower() or "ghostcomp" in result.lower()

    def test_matching_style_reports_no_missing_styles(self):
        # MockReader.get_component_spec returns styles_by_state.default = [{"property": "color", "value": "red"}]
        result = _dispatcher(1).dispatch(
            "validate_component_implementation",
            {"name": "BtnPrimary", "jsx_source": '<button style={{color: "red"}}>OK</button>'},
            "doc1",
        )
        assert "✅" in result
        assert "ausentes" not in result.lower() or "estilos default ausentes" not in result.lower()

    def test_missing_style_is_flagged(self):
        result = _dispatcher(1).dispatch(
            "validate_component_implementation",
            {"name": "BtnPrimary", "jsx_source": "<button>OK</button>"},
            "doc1",
        )
        assert "ausentes" in result.lower()
        assert "color" in result and "red" in result

    def test_oversized_jsx_source_is_rejected_before_extraction(self):
        # C34: jsx_source is agent-submitted text re-run through the same
        # regex extractor used for a whole prototype bundle — must be
        # bounded, unlike a local file whose size the project doesn't control.
        from design_graph.mcp.tools import _MAX_VALIDATION_JSX_SOURCE_CHARS
        oversized = "<div>" + ("x" * _MAX_VALIDATION_JSX_SOURCE_CHARS) + "</div>"
        result = _dispatcher(1).dispatch(
            "validate_component_implementation",
            {"name": "BtnPrimary", "jsx_source": oversized}, "doc1",
        )
        assert "muito grande" in result.lower()

    def test_jsx_source_within_limit_is_processed_normally(self):
        result = _dispatcher(1).dispatch(
            "validate_component_implementation",
            {"name": "BtnPrimary", "jsx_source": '<button style={{color: "red"}}>OK</button>'},
            "doc1",
        )
        assert "muito grande" not in result.lower()

    def test_output_carries_best_effort_caveat(self):
        result = _dispatcher(1).dispatch(
            "validate_component_implementation",
            {"name": "BtnPrimary", "jsx_source": "<button>OK</button>"},
            "doc1",
        )
        assert "best-effort" in result.lower() or "não verifica" in result.lower()


class TestToolDefinitions:
    def test_all_standard_tools_defined(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        expected = {
            "list_screens", "get_screen", "get_section", "get_component",
            "get_tokens", "find_token_usage", "search", "impact",
            "get_full_jsx", "get_full_styles", "get_component_interactions",
            "get_component_children", "list_components", "get_component_spec",
            "get_component_full", "set_prototype",
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

    def test_set_prototype_malformed_name_falls_through_to_not_found(self):
        # C27/T52: same defense-in-depth reuse of GraphDocumentName as
        # _find_reader — must not raise, just report "not found".
        server = self._server(2)
        result = server.dispatch_tool_call("set_prototype", {"name": "../etc/passwd"})
        assert result.is_error is False
        assert "not found" in result.text.lower()
        assert not server._active_doc
