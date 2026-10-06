"""Tests for mcp/tools.py and mcp/server.py — T15."""

import pytest

from design_graph.model.graph.reader import NamedEntity, NamedEntityResolution
from design_graph.interface.mcp.server import MCPServer
from design_graph.interface.mcp.tool_definitions import TOOL_DEFINITIONS
from design_graph.interface.mcp import build_tools
from design_graph.interface.mcp.tools import ToolDispatcher


# ── Mock reader ───────────────────────────────────────────────────────────────

class MockReader:
    def model_info(self):
        return {"version": 10, "capture": "html_prototype"}

    """Minimal GraphReader stub for MCP unit tests."""

    def list_screens(self):
        return [{"name": "RestaurantsPage", "component_count": 3,
                 "sections_count": 2, "top_components": ["SectionCard", "BtnPrimary"]}]

    def get_screen(self, name):
        if "Restaurants" in name:
            return {"name": "RestaurantsPage", "component_count": 3,
                    "sections_count": 2, "components": [], "sections": [], "texts": []}
        return None

    def resolve_named_entity(self, name):
        if "Ghost" in name or "Nonexistent" in name or name == "page-title":
            return NamedEntityResolution()
        return NamedEntityResolution(entity=NamedEntity("component", name))

    def get_screen_texts(self, name):
        return {"name": name, "texts": []}

    def get_component(self, name):
        return {"c.name": name, "c.comp_type": "card", "c.source_code": "<div/>", "c.source_lang": "jsx",
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
    def get_full_source(self, name):
        return {"source_code": "<div>full jsx</div>", "source_lang": "jsx"}
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
            "component_refs": [], "texts": [f"text{i}" for i in range(10)], "source_code": "", "source_lang": "jsx",
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
                "c.source_code": "<div/>", "c.source_lang": "jsx", "c.occurrence": 1, "c.classes": "",
                "styles_by_state": {
                    "default": [{"property": f"prop{i}", "value": f"val{i}"} for i in range(15)],
                },
                "tokens": [], "texts": [], "interactions": [],
                "children": [], "parents": [], "screens_using": [],
            }
        if name == "ManyTextsComp":
            return {
                "c.name": name, "c.comp_type": "card",
                "c.source_code": "<div/>", "c.source_lang": "jsx", "c.occurrence": 1, "c.classes": "",
                "styles_by_state": {},
                "tokens": [], "interactions": [],
                "texts": [{"t.content": f"text{i}", "t.text_type": "label"} for i in range(10)],
                "children": [], "parents": [], "screens_using": [],
            }
        if name == "Icon":
            return {
                "c.name": name, "c.comp_type": "component",
                "c.source_code": "<svg/>", "c.source_lang": "jsx", "c.occurrence": 1, "c.classes": "",
                "styles_by_state": {}, "tokens": [], "texts": [], "interactions": [],
                "children": [], "parents": [], "screens_using": [],
                "referenced_data": {"ICONS": {"lock": "M21 2l-2 2", "trash": "M3 6h18"}},
            }
        if name == "ResponsiveOnlyComp":
            return {
                "c.name": name, "c.comp_type": "card",
                "c.source_code": "<div/>", "c.source_lang": "jsx", "c.occurrence": 1, "c.classes": "",
                "styles_by_state": {},
                "responsive_styles_by_media": {
                    "(max-width: 600px)": [{"property": f"prop{i}", "value": f"val{i}"} for i in range(15)],
                },
                "tokens": [], "texts": [], "interactions": [],
                "children": [], "parents": [], "screens_using": [],
            }
        if name == "MixedResponsiveComp":
            return {
                "c.name": name, "c.comp_type": "card",
                "c.source_code": "<div/>", "c.source_lang": "jsx", "c.occurrence": 1, "c.classes": "",
                "styles_by_state": {"default": [{"property": "color", "value": "red"}]},
                "responsive_styles_by_media": {
                    "(max-width: 600px)": [{"property": "color", "value": "blue"}],
                },
                "tokens": [], "texts": [], "interactions": [],
                "children": [], "parents": [], "screens_using": [],
            }
        if name == "ManyRefDataComp":
            return {
                "c.name": name, "c.comp_type": "component",
                "c.source_code": "<svg/>", "c.source_lang": "jsx", "c.occurrence": 1, "c.classes": "",
                "styles_by_state": {}, "tokens": [], "texts": [], "interactions": [],
                "children": [], "parents": [], "screens_using": [],
                "referenced_data": {"ICONS": {f"icon{i}": f"M{i} 0 0" for i in range(35)}},
            }
        return {
            "c.name": name, "c.comp_type": "button",
            "c.source_code": "<button/>", "c.source_lang": "jsx", "c.occurrence": 5, "c.classes": "",
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

    def get_component_full(self, name, depth=3):
        if "Ghost" in name or "Nonexistent" in name:
            return None
        root_texts = (
            [{"content": f"text{i}", "text_type": "label"} for i in range(10)]
            if name == "ManyTextsComp" else []
        )
        return {
            "root": name,
            "components": [
                {
                    "name": name, "comp_type": "card", "source_code": "<div/>", "source_lang": "jsx", "declares_inline_styles": False,
                    "occurrence": 2, "classes": "",
                    "styles_by_state": {"default": [{"property": "display", "value": "flex"}]},
                    "tokens": [], "texts": root_texts, "interactions": [], "props": [],
                    "children": ["Badge"],
                },
                {
                    "name": "Badge", "comp_type": "badge", "source_code": "<span/>", "source_lang": "jsx", "declares_inline_styles": False,
                    "occurrence": 1, "classes": "",
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


class _ComponentHierarchyReader:
    """
    One component with a known parent and a known owning screen. A search
    hit used to render as just its name/type/detail — an agent had to spend
    a follow-up get_component_spec() call just to learn where a matched
    component lives in the tree, even though the graph already has that
    edge (see docs/investigation/design-graph-findings.md).
    """

    def list_screens(self):
        return [{"name": "TeamsView", "component_count": 1,
                  "sections_count": 0, "top_components": ["MemberRow"]}]

    def list_components(self, comp_type=None):
        return [{"c.name": "MemberRow", "c.comp_type": "list-item", "c.occurrence": 1}]

    def get_tokens(self, category=None):
        return []

    def list_texts(self):
        return []

    def list_shared_style_classes(self):
        return []

    def get_component_parents(self, name):
        return ["TeamsSection"]

    def find_screens_using_comp_transitively(self, comp_name):
        return ["TeamsView"]


class TestSearchRendersComponentHierarchy:
    def test_component_hit_shows_parent_and_owning_screen(self):
        d = ToolDispatcher([("doc1", _ComponentHierarchyReader())])
        result = d.dispatch("search", {"query": "MemberRow"}, "doc1")
        assert "TeamsSection" in result
        assert "TeamsView" in result


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
        assert "get_component" in names

    def test_tool_requires_name_in_schema(self):
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "get_component")
        assert "name" in tool["inputSchema"].get("required", [])

    def test_dispatch_known_component_returns_markdown(self):
        result = _dispatcher(1).dispatch("get_component", {"name": "BtnPrimary"}, "doc1")
        assert isinstance(result, str)
        assert "BtnPrimary" in result

    def test_dispatch_unknown_returns_not_found_message(self):
        result = _dispatcher(1).dispatch("get_component", {"name": "GhostComp"}, "doc1")
        assert "not found" in result.lower() or "ghostcomp" in result.lower()

    def test_output_contains_style_section(self):
        result = _dispatcher(1).dispatch("get_component", {"name": "BtnPrimary"}, "doc1")
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
        result = _dispatcher(1).dispatch("get_component", {"name": "page-title"}, "doc1")
        assert "font-size" in result
        assert "25px" in result

    def test_labeled_as_css_class_not_component(self):
        result = _dispatcher(1).dispatch("get_component", {"name": "page-title"}, "doc1")
        assert "classe css" in result.lower() or "css class" in result.lower()

    def test_reports_screen_using_the_class(self):
        result = _dispatcher(1).dispatch("get_component", {"name": "page-title"}, "doc1")
        assert "Applications" in result

    def test_real_component_match_never_falls_back(self):
        """A genuine component hit must win outright — the class fallback
        only runs when component resolution finds literally nothing."""
        result = _dispatcher(1).dispatch("get_component", {"name": "BtnPrimary"}, "doc1")
        assert "classe css" not in result.lower()

    def test_unknown_name_that_is_also_not_a_class_stays_not_found(self):
        result = _dispatcher(1).dispatch("get_component", {"name": "GhostComp"}, "doc1")
        assert "not found" in result.lower() or "ghostcomp" in result.lower()


class TestGetFullStylesTool:
    """
    get_full_source has no style equivalent — get_section/get_screen_full/
    get_component_spec all truncate their style tables (`+N mais`) with no
    way to recover what was cut. get_full_styles renders the reader's
    already-complete data (the cap is a display-layer slice, not a query
    limit) without slicing it (see docs/changes/C36).
    """

    def test_tool_in_definitions(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "get_full" in names

    def test_section_styles_are_not_truncated(self):
        result = _dispatcher(1).dispatch("get_full", {"aspect": "styles", "screen": "HistoryView", "section": "Header"}, "doc1",
        )
        assert "prop9" in result  # 10th entry — beyond any display cap
        assert "mais" not in result.lower()

    def test_section_styles_grouped_by_selector(self):
        result = _dispatcher(1).dispatch("get_full", {"aspect": "styles", "screen": "HistoryView", "section": "Header"}, "doc1",
        )
        assert ".audit-item" in result
        assert ".audit-dot" in result

    def test_unknown_section_returns_not_found_message(self):
        result = _dispatcher(1).dispatch("get_full", {"aspect": "styles", "screen": "HistoryView", "section": "Ghost"}, "doc1",
        )
        assert "não encontrada" in result.lower() or "not found" in result.lower()

    def test_component_styles_are_not_truncated(self):
        result = _dispatcher(1).dispatch("get_full", {"aspect": "styles", "name": "ManyStylesComp"}, "doc1")
        assert "prop14" in result  # 15th entry — beyond the 12-item display cap
        assert "mais" not in result.lower()

    def test_responsive_styles_are_not_truncated(self):
        """
        get_component_spec's own "Estilos responsivos" section truncates
        each @media condition's table at 12 rows with no way back —
        get_full_styles is the only escape hatch, and previously didn't
        render @media data at all (docs/changes/C41).
        """
        result = _dispatcher(1).dispatch("get_full", {"aspect": "styles", "name": "ResponsiveOnlyComp"}, "doc1")
        assert "prop14" in result  # 15th entry — beyond the 12-item display cap
        assert "mais" not in result.lower()
        assert "(max-width: 600px)" in result

    def test_component_with_only_responsive_styles_is_not_reported_as_styleless(self):
        # Previously: styles_by_state empty -> "Nenhum estilo encontrado",
        # even when the component has real @media-scoped styles.
        result = _dispatcher(1).dispatch("get_full", {"aspect": "styles", "name": "ResponsiveOnlyComp"}, "doc1")
        assert "nenhum estilo encontrado" not in result.lower()

    def test_default_and_responsive_styles_both_shown_without_mixing(self):
        result = _dispatcher(1).dispatch("get_full", {"aspect": "styles", "name": "MixedResponsiveComp"}, "doc1")
        assert "Estado: default" in result
        assert "@media (max-width: 600px)" in result

    def test_falls_back_to_shared_css_class_when_no_component_matches(self):
        """
        get_component_spec("page-title") falls back to find_styles_by_class
        when no component matches — get_full_styles(name="page-title") must
        do the same, or a class-only lookup silently works through one tool
        and not its "full" counterpart (reported gap, docs/changes/C37).
        """
        result = _dispatcher(1).dispatch("get_full", {"aspect": "styles", "name": "page-title"}, "doc1")
        assert "font-size" in result
        assert "25px" in result

    def test_unknown_component_returns_not_found_message(self):
        result = _dispatcher(1).dispatch("get_full", {"aspect": "styles", "name": "GhostComp"}, "doc1")
        assert "não encontrado" in result.lower() or "not found" in result.lower()

    def test_neither_name_nor_screen_section_given(self):
        result = _dispatcher(1).dispatch("get_full", {"aspect": "styles", }, "doc1")
        assert "name" in result.lower() or "screen" in result.lower()


class TestGetFullTextsTool:
    """
    get_section/get_screen_full/get_component_spec/get_component_full all
    truncate their text list ("+N mais") with no way to recover what was
    cut — the same gap C36 already closed for styles via get_full_styles.
    get_full_texts mirrors that fix for texts (docs/changes/C38).
    """

    def test_tool_in_definitions(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "get_full" in names

    def test_section_texts_are_not_truncated(self):
        result = _dispatcher(1).dispatch("get_full", {"aspect": "texts", "screen": "HistoryView", "section": "Header"}, "doc1",
        )
        assert "text9" in result  # 10th entry — beyond any display cap
        assert "mais" not in result.lower()

    def test_unknown_section_returns_not_found_message(self):
        result = _dispatcher(1).dispatch("get_full", {"aspect": "texts", "screen": "HistoryView", "section": "Ghost"}, "doc1",
        )
        assert "não encontrada" in result.lower() or "not found" in result.lower()

    def test_component_texts_are_not_truncated(self):
        result = _dispatcher(1).dispatch("get_full", {"aspect": "texts", "name": "ManyTextsComp"}, "doc1")
        assert "text9" in result  # 10th entry — beyond the 8-item display cap
        assert "mais" not in result.lower()

    def test_unknown_component_returns_not_found_message(self):
        result = _dispatcher(1).dispatch("get_full", {"aspect": "texts", "name": "GhostComp"}, "doc1")
        assert "não encontrado" in result.lower() or "not found" in result.lower()

    def test_neither_name_nor_screen_section_given(self):
        result = _dispatcher(1).dispatch("get_full", {"aspect": "texts", }, "doc1")
        assert "name" in result.lower() or "screen" in result.lower()


class TestTruncationNoticesPointToFullTools:
    """
    A truncated list is only actually recoverable if its notice names the
    exact call to make — a bare "+N mais" with no pointer is what Achado 2
    (docs/investigation/design-graph-findings.md) flagged as misleading.
    """

    def test_component_spec_texts_point_to_get_full(name="self", aspect="texts"):
        result = _dispatcher(1).dispatch("get_component", {"name": "ManyTextsComp"}, "doc1")
        assert 'get_full(name="ManyTextsComp", aspect="texts")' in result

    def test_component_spec_styles_point_to_get_full(name="self", aspect="styles"):
        result = _dispatcher(1).dispatch("get_component", {"name": "ManyStylesComp"}, "doc1")
        assert 'get_full(name="ManyStylesComp", aspect="styles")' in result

    def test_component_full_texts_point_to_get_full(name="self", aspect="texts"):
        result = _dispatcher(1).dispatch("get_component", {"depth": 3, "name": "ManyTextsComp"}, "doc1")
        assert 'get_full(name="ManyTextsComp", aspect="texts")' in result

    def test_component_spec_responsive_styles_point_to_get_full(name="self", aspect="styles"):
        result = _dispatcher(1).dispatch("get_component", {"name": "ResponsiveOnlyComp"}, "doc1")
        assert 'get_full(name="ResponsiveOnlyComp", aspect="styles")' in result


class TestReferencedDataInComponentSpec:
    """
    A component whose own body references a module-level constant by name
    (e.g. ICONS[name]) has that constant's literal content rendered in its
    spec — the mechanism that lets an agent reuse the prototype's own exact
    icon paths instead of substituting a different icon set (docs/changes/C39).
    """

    def test_referenced_data_section_present(self):
        result = _dispatcher(1).dispatch("get_component", {"name": "Icon"}, "doc1")
        assert "Dados referenciados" in result
        assert "ICONS" in result

    def test_referenced_data_values_shown(self):
        result = _dispatcher(1).dispatch("get_component", {"name": "Icon"}, "doc1")
        assert "M21 2l-2 2" in result
        assert "M3 6h18" in result

    def test_no_section_when_component_has_no_referenced_data(self):
        result = _dispatcher(1).dispatch("get_component", {"name": "BtnPrimary"}, "doc1")
        assert "Dados referenciados" not in result

    def test_large_table_is_truncated_with_pointer_to_get_full(name="self", aspect="data"):
        result = _dispatcher(1).dispatch("get_component", {"name": "ManyRefDataComp"}, "doc1")
        assert "mais" in result.lower()
        assert 'get_full(name="ManyRefDataComp", aspect="data")' in result


class TestGetComponentDataTool:
    def test_tool_in_definitions(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "get_full" in names

    def test_returns_complete_uncapped_table(self):
        result = _dispatcher(1).dispatch("get_full", {"aspect": "data", "name": "ManyRefDataComp"}, "doc1")
        assert "icon34" in result  # 35th entry — beyond the 30-item display cap
        assert "mais" not in result.lower()

    def test_returns_full_values_for_small_table(self):
        result = _dispatcher(1).dispatch("get_full", {"aspect": "data", "name": "Icon"}, "doc1")
        assert "M21 2l-2 2" in result
        assert "M3 6h18" in result

    def test_unknown_component_returns_not_found_message(self):
        result = _dispatcher(1).dispatch("get_full", {"aspect": "data", "name": "GhostComp"}, "doc1")
        assert "não encontrado" in result.lower()

    def test_component_without_referenced_data_returns_explanatory_message(self):
        result = _dispatcher(1).dispatch("get_full", {"aspect": "data", "name": "BtnPrimary"}, "doc1")
        assert "nenhum dado referenciado" in result.lower()


class TestGetBuildDiffSkippedEntriesNotice:
    """
    RawSources.skipped_entries (bundle entries that failed to decode) was
    previously only ever logged to stderr during a build — never
    queryable through any MCP tool. get_build_diff now surfaces it
    regardless of which message it would otherwise return (docs/changes/C39).
    """

    class _StubReader:
        def __init__(self, diff):
            self._diff = diff

        def get_build_diff(self):
            return self._diff

    def test_warns_on_first_build_when_entries_were_skipped(self):
        result = build_tools.get_build_diff(self._StubReader({"is_first_build": True, "skipped_entries": 2}))
        assert "2 entrada" in result
        assert "falharam ao decodificar" in result

    def test_warns_when_no_screen_or_component_changes(self):
        diff = {"is_first_build": False, "screens_added": [], "screens_removed": [],
                "comps_added": [], "comps_removed": [], "skipped_entries": 1}
        result = build_tools.get_build_diff(self._StubReader(diff))
        assert "1 entrada" in result
        assert "Nenhuma mudança" in result

    def test_warns_alongside_a_real_diff(self):
        diff = {"is_first_build": False, "screens_added": ["NewPage"], "screens_removed": [],
                "comps_added": [], "comps_removed": [], "skipped_entries": 1}
        result = build_tools.get_build_diff(self._StubReader(diff))
        assert "1 entrada" in result
        assert "NewPage" in result

    def test_no_notice_when_nothing_was_skipped(self):
        result = build_tools.get_build_diff(self._StubReader({"is_first_build": True, "skipped_entries": 0}))
        assert "falharam ao decodificar" not in result


class TestGetComponentFullTool:
    def test_tool_in_definitions(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "get_component" in names

    def test_tool_requires_name_in_schema(self):
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "get_component")
        assert "name" in tool["inputSchema"].get("required", [])

    def test_dispatch_known_component_returns_markdown_with_descendants(self):
        result = _dispatcher(1).dispatch("get_component", {"depth": 3, "name": "BtnPrimary"}, "doc1")
        assert isinstance(result, str)
        assert "BtnPrimary" in result
        assert "Badge" in result  # descendant included, not just the root

    def test_dispatch_unknown_returns_not_found_message(self):
        result = _dispatcher(1).dispatch("get_component", {"depth": 3, "name": "GhostComp"}, "doc1")
        assert "não encontrado" in result.lower() or "ghostcomp" in result.lower()

    def test_root_marked_in_output(self):
        result = _dispatcher(1).dispatch("get_component", {"depth": 3, "name": "BtnPrimary"}, "doc1")
        assert "(raiz)" in result


class TestValidateComponentImplementationTool:
    def test_tool_in_definitions(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "validate_component_implementation" in names

    def test_tool_requires_name_and_source(self):
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "validate_component_implementation")
        required = tool["inputSchema"].get("required", [])
        assert "name" in required and "source" in required

    def test_empty_source_reports_nothing_to_compare(self):
        result = _dispatcher(1).dispatch(
            "validate_component_implementation", {"name": "BtnPrimary", "source": ""}, "doc1",
        )
        assert "vazio" in result.lower()

    def test_unknown_component_reports_not_found(self):
        result = _dispatcher(1).dispatch(
            "validate_component_implementation",
            {"name": "GhostComp", "source": "<div/>"}, "doc1",
        )
        assert "não encontrado" in result.lower() or "ghostcomp" in result.lower()

    def test_matching_style_reports_no_missing_styles(self):
        # MockReader.get_component_spec returns styles_by_state.default = [{"property": "color", "value": "red"}]
        result = _dispatcher(1).dispatch(
            "validate_component_implementation",
            {"name": "BtnPrimary", "source": '<button style={{color: "red"}}>OK</button>'},
            "doc1",
        )
        assert "✅" in result
        assert "ausentes" not in result.lower() or "estilos default ausentes" not in result.lower()

    def test_missing_style_is_flagged(self):
        result = _dispatcher(1).dispatch(
            "validate_component_implementation",
            {"name": "BtnPrimary", "source": "<button>OK</button>"},
            "doc1",
        )
        assert "ausentes" in result.lower()
        assert "color" in result and "red" in result

    def test_oversized_source_is_rejected_before_extraction(self):
        # C34: source is agent-submitted text re-run through the same
        # regex extractor used for a whole prototype bundle — must be
        # bounded, unlike a local file whose size the project doesn't control.
        from design_graph.interface.mcp.validation_tool import MAX_VALIDATION_SOURCE_CHARS
        oversized = "<div>" + ("x" * MAX_VALIDATION_SOURCE_CHARS) + "</div>"
        result = _dispatcher(1).dispatch(
            "validate_component_implementation",
            {"name": "BtnPrimary", "source": oversized}, "doc1",
        )
        assert "muito grande" in result.lower()

    def test_source_within_limit_is_processed_normally(self):
        result = _dispatcher(1).dispatch(
            "validate_component_implementation",
            {"name": "BtnPrimary", "source": '<button style={{color: "red"}}>OK</button>'},
            "doc1",
        )
        assert "muito grande" not in result.lower()

    def test_output_carries_best_effort_caveat(self):
        result = _dispatcher(1).dispatch(
            "validate_component_implementation",
            {"name": "BtnPrimary", "source": "<button>OK</button>"},
            "doc1",
        )
        assert "best-effort" in result.lower() or "não verifica" in result.lower()



    def test_graph_without_a_recorded_capture_asks_for_a_rebuild(self):
        class LegacyReader(MockReader):
            def model_info(self):
                return None

        result = ToolDispatcher([("doc1", LegacyReader())]).dispatch(
            "validate_component_implementation", {"name": "BtnPrimary", "source": "<div/>"}, "doc1",
        )
        assert "--force" in result

    def test_unreadable_fragment_is_reported(self):
        class OtherCaptureReader(MockReader):
            def model_info(self):
                return {"version": 10, "capture": "no_such_capture"}

        result = ToolDispatcher([("doc1", OtherCaptureReader())]).dispatch(
            "validate_component_implementation", {"name": "BtnPrimary", "source": "<div/>"}, "doc1",
        )
        assert "no_such_capture" in result

class TestToolDefinitions:
    def test_all_standard_tools_defined(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        expected = {
            "list_screens", "list_components", "search", "assemble_page", "get_screen", "get_component",
            "get_full", "get_tokens", "get_resources", "get_asset", "impact",
            "validate_component_implementation", "set_prototype", "get_build_diff", "get_metrics",
        }
        assert names == expected

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
        assert "get_component" in names

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


# ── get_metrics tool ─────────────────────────────────────────────────────────
#
# get_metrics reads mcp/metrics.py's call log — never a GraphReader — so it
# is special-cased in ToolDispatcher.dispatch() alongside list_screens/search,
# before pick_reader() runs, and must work with zero prototypes loaded.

def _metric_record(**overrides):
    from design_graph.interface.mcp.metrics import CallRecord

    defaults = dict(
        timestamp="2026-01-01T00:00:00.000+00:00", tool="search", prototype="toToggle",
        outcome="ok", duration_ms=1.0, response_chars=10, arguments={"query": "x"},
    )
    defaults.update(overrides)
    return CallRecord(**defaults)


class TestGetMetricsTool:
    def test_tool_in_definitions(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "get_metrics" in names

    def test_works_with_zero_prototypes_loaded(self, monkeypatch):
        monkeypatch.setattr("design_graph.interface.mcp.metrics.query_calls", lambda **kwargs: [])
        d = ToolDispatcher([])
        result = d.dispatch("get_metrics", {}, "")
        assert isinstance(result, str)

    def test_empty_state_message(self, monkeypatch):
        monkeypatch.setattr("design_graph.interface.mcp.metrics.query_calls", lambda **kwargs: [])
        d = ToolDispatcher([])
        result = d.dispatch("get_metrics", {}, "")
        assert "Nenhuma chamada" in result

    def test_aggregate_shows_by_tool_breakdown_and_not_ok_rate(self, monkeypatch):
        records = [_metric_record(tool="search", outcome="ok"),
                   _metric_record(tool="search", outcome="no_results")]
        monkeypatch.setattr("design_graph.interface.mcp.metrics.query_calls", lambda **kwargs: records)
        result = ToolDispatcher([]).dispatch("get_metrics", {}, "")
        assert "search" in result
        assert "Taxa não-ok" in result

    def test_aggregate_shows_by_prototype_section(self, monkeypatch):
        records = [_metric_record(prototype="toToggle"), _metric_record(prototype="ipede-v7")]
        monkeypatch.setattr("design_graph.interface.mcp.metrics.query_calls", lambda **kwargs: records)
        result = ToolDispatcher([]).dispatch("get_metrics", {}, "")
        assert "toToggle" in result
        assert "ipede-v7" in result

    def test_aggregate_shows_top_empty_queries(self, monkeypatch):
        records = [_metric_record(tool="search", outcome="no_results",
                                   arguments={"query": "botao cinza"})] * 2
        monkeypatch.setattr("design_graph.interface.mcp.metrics.query_calls", lambda **kwargs: records)
        result = ToolDispatcher([]).dispatch("get_metrics", {}, "")
        assert "botao cinza" in result

    def test_filters_thread_through_to_query_calls(self, monkeypatch):
        captured = {}

        def _stub(**kwargs):
            captured.update(kwargs)
            return []

        monkeypatch.setattr("design_graph.interface.mcp.metrics.query_calls", _stub)
        ToolDispatcher([]).dispatch(
            "get_metrics",
            {"doc": "toToggle", "tool": "search", "outcome": "ok",
             "since": "24h", "until": "2026-01-01T00:00:00Z"},
            "",
        )
        assert captured["prototype"] == "toToggle"
        assert captured["tool"] == "search"
        assert captured["outcome"] == "ok"
        assert captured["since"] == "24h"
        assert captured["until"] == "2026-01-01T00:00:00Z"

    def test_raw_mode_renders_call_table_instead_of_summary(self, monkeypatch):
        records = [_metric_record(tool="search")]
        monkeypatch.setattr("design_graph.interface.mcp.metrics.query_calls", lambda **kwargs: records)
        result = ToolDispatcher([]).dispatch("get_metrics", {"raw": True}, "")
        assert "Chamadas registradas" in result
        assert "Taxa não-ok" not in result

    def test_limit_does_not_affect_aggregate_total(self, monkeypatch):
        records = [_metric_record() for _ in range(10)]
        monkeypatch.setattr("design_graph.interface.mcp.metrics.query_calls", lambda **kwargs: records)
        result = ToolDispatcher([]).dispatch("get_metrics", {"limit": 2}, "")
        assert "(10 chamadas)" in result

    def test_raw_mode_limit_truncates_shown_rows(self, monkeypatch):
        records = [_metric_record(timestamp=f"2026-01-01T00:00:0{i}.000+00:00") for i in range(5)]
        monkeypatch.setattr("design_graph.interface.mcp.metrics.query_calls", lambda **kwargs: records)
        result = ToolDispatcher([]).dispatch("get_metrics", {"raw": True, "limit": 2}, "")
        assert "+3 mais" in result


class TestGetTokensModes:
    class _Reader(MockReader):
        def __init__(self):
            self.calls = []

        def get_tokens(self, category=None, screen=None, mode=None):
            self.calls.append((category, screen, mode))
            return [
                {"t.category": "css_var", "t.label": "--accent", "t.value": "#5FB0B0", "t.usage": 3, "t.mode": "escuro"},
                {"t.category": "spacing", "t.label": "space_16", "t.value": "16px", "t.usage": 4, "t.mode": ""},
            ]

    def test_mode_argument_reaches_the_reader(self):
        reader = self._Reader()
        ToolDispatcher([("doc1", reader)]).dispatch("get_tokens", {"mode": "escuro"}, "doc1")
        assert reader.calls == [(None, None, "escuro")]

    def test_each_token_shows_its_mode_when_it_has_one(self):
        out = ToolDispatcher([("doc1", self._Reader())]).dispatch("get_tokens", {}, "doc1")
        assert "- **--accent** [escuro]: `#5FB0B0`" in out
        assert "- **space_16**: `16px`" in out

    def test_mode_is_an_input_of_the_tool(self):
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "get_tokens")
        assert "mode" in tool["inputSchema"]["properties"]



class TestGetComponentRouting:
    """get_component answers with the spec, or with the nested tree when depth is given."""

    def test_depth_must_be_between_0_and_3(self):
        from design_graph.interface.mcp import component_tools

        assert "depth inválido" in component_tools.get_component(MockReader(), "BtnPrimary", depth=7)
        assert "depth inválido" in component_tools.get_component(MockReader(), "BtnPrimary", depth="x")


class TestImpactCoversTokenValues:
    """impact answers "who uses X" for a component, a screen, a token's name — and a literal value."""

    class _Reader:
        def get_impact(self, name):
            return {"found": False}

        def find_token_usage(self, value):
            if value != "#FFB81C":
                return []
            return [{"t.label": "accent", "t.value": "#FFB81C", "t.category": "color",
                     "components": [{"c.name": "BtnPrimary"}], "screens": ["Home"]}]

    def test_a_literal_value_lists_its_tokens_and_who_uses_them(self):
        out = ToolDispatcher([("doc", self._Reader())]).dispatch("impact", {"name": "#FFB81C"}, "doc")
        assert "accent" in out and "BtnPrimary" in out and "Home" in out

    def test_nothing_found_says_so(self):
        assert "não encontrado" in ToolDispatcher([("doc", self._Reader())]).dispatch("impact", {"name": "#000"}, "doc")

    def test_find_token_usage_is_gone(self):
        assert "find_token_usage" not in {t["name"] for t in TOOL_DEFINITIONS}
