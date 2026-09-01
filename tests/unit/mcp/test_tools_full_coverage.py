"""
Targeted tests for mcp/tools.py branches not covered by test_tools.py.

Covers:
  - pick_reader: active_doc stale (exists in session but not in readers)
  - get_section: found vs not found, content rendering (styles, texts, jsx)
  - get_component: with styles, tokens, children present
  - find_token_usage: token found vs not found
  - impact: component path vs token path
  - get_full_jsx: found vs not found
  - get_component_interactions: with data
  - _find_reader: substring match fallback
"""

from __future__ import annotations

import pytest

from design_graph.mcp.tools import TOOL_DEFINITIONS, ToolDispatcher, _truncated_fields_notice


# ── Rich mock reader ──────────────────────────────────────────────────────────

class RichMockReader:
    """Extended mock with richer return values to exercise all formatting branches."""

    def list_screens(self):
        return [{"name": "RestaurantsPage", "component_count": 3,
                 "sections_count": 1, "top_components": ["BtnPrimary"]}]

    def get_screen(self, name):
        if "Restaurants" in name:
            return {
                "name": "RestaurantsPage", "component_count": 3, "sections_count": 1,
                "components": [
                    {"c.name": "BtnPrimary", "c.comp_type": "button"},
                    {"c.name": "SectionCard", "c.comp_type": "card"},
                ],
                "sections": [{
                    "sec.name": "Header",
                    "sec.components_json": '["BtnPrimary"]',
                    "components_json": '["BtnPrimary"]',
                }],
                "texts": [],
            }
        return None

    def get_section(self, screen, section_hint):
        if "Header" in section_hint or "head" in section_hint.lower():
            return {
                "id": "sec_hdr", "name": "Header",
                "detection_method": "comment",
                "styles_by_element": {
                    "(estilo da seção)": [
                        {"property": "padding", "value": "16px"},
                        {"property": "margin", "value": "8px"},
                    ],
                },
                "component_refs": ["BtnPrimary"],
                "texts": ["Restaurantes"],
                "jsx_snippet": "<div>header jsx</div>",
            }
        return None

    def get_component(self, name):
        if name == "BtnWithStyles":
            return {
                "c.name": "BtnWithStyles", "c.comp_type": "button",
                "c.jsx_snippet": "<button>OK</button>",
                "c.occurrence": 3, "c.classes": "btn",
                "styles": [
                    {"s.state": "default",    "s.property": "backgroundColor", "s.value": "#ffb81c"},
                    {"s.state": "hover",      "s.property": "backgroundColor", "s.value": "#f59e0b"},
                    {"s.state": "focus",      "s.property": "outline",         "s.value": "2px"},
                    {"s.state": "transition", "s.property": "all",             "s.value": "0.2s"},
                ],
                "tokens": [{"t.label": "primary", "t.value": "#ffb81c", "t.category": "color"}],
                "children": ["Badge", "Icon"],
                "texts": [], "interactions": [],
                "screens_using": ["RestaurantsPage"],
            }
        return {"c.name": name, "c.comp_type": "card", "c.jsx_snippet": "",
                "c.occurrence": 1, "c.classes": "",
                "styles": [], "tokens": [], "children": [], "texts": [],
                "interactions": [], "screens_using": []}

    def get_component_children(self, name):
        return ["Badge", "Icon"] if name == "BtnWithStyles" else []

    def get_component_parents(self, name): return []

    def get_tokens(self, category=None):
        return [{"t.label": "primary", "t.value": "#ffb81c",
                 "t.category": "color", "t.id": "col_1", "t.usage": 5}]

    def find_token_usage(self, value):
        if "#ffb81c" in value or "primary" in value:
            return [{
                "t.label": "primary", "t.value": "#ffb81c",
                "t.category": "color", "t.id": "col_1",
                "components": [{"c.name": "BtnPrimary"}],
                "screens": ["RestaurantsPage"],
            }]
        return []

    def get_interactions(self, comp_name):
        if comp_name == "BtnHover":
            return [{
                "i.trigger": "hover",
                "i.css_prop": "backgroundColor",
                "i.from_val": "#ffb81c",
                "i.to_val": "#f59e0b",
                "i.transition": "all 0.2s ease",
            }]
        return []

    def get_full_jsx(self, name):
        if name == "BtnPrimary":
            return "<button style={{color:'#ffb81c'}}>Click</button>"
        if name == "BasicTab":
            return "<div>{[conditional:Chip]}</div>"
        return ""

    def get_impact(self, name):
        if name == "BtnPrimary":
            return {"found": True, "type": "button",
                    "screens": ["RestaurantsPage"], "sections": [], "tokens_used": []}
        if name == "primary":
            return {"found": True, "label": "primary", "value": "#ffb81c",
                    "components": ["BtnPrimary"], "screens": ["RestaurantsPage"]}
        return {"found": False}

    def find_screens_using_comp_transitively(self, name): return []
    def count_nodes(self): return {}
    def get_screen_names(self): return ["RestaurantsPage"]


def _dispatcher(n=1):
    readers = [(f"doc{i}", RichMockReader()) for i in range(1, n + 1)]
    return ToolDispatcher(readers)


# ── pick_reader: stale active_doc ─────────────────────────────────────────────

class TestPickReaderStaleSessions:
    def test_stale_active_doc_returns_error_with_guidance(self):
        d = _dispatcher(2)
        reader, err = d.pick_reader(doc=None, active_doc="prototype_that_was_removed")
        assert reader is None
        assert err is not None
        assert "prototype_that_was_removed" in err

    def test_stale_active_doc_error_lists_available(self):
        d = ToolDispatcher([("alpha", RichMockReader()), ("beta", RichMockReader())])
        _, err = d.pick_reader(doc=None, active_doc="gone")
        assert "alpha" in err or "beta" in err


# ── get_section ───────────────────────────────────────────────────────────────

class TestGetSectionTool:
    def _d(self):
        return ToolDispatcher([("doc", RichMockReader())])

    def test_found_section_contains_section_name(self):
        d = self._d()
        r, _ = d.pick_reader(doc="doc", active_doc="")
        result = d.get_section(r, "RestaurantsPage", "Header")
        assert "Header" in result

    def test_section_with_styles_included(self):
        d = self._d()
        r, _ = d.pick_reader(doc="doc", active_doc="")
        result = d.get_section(r, "RestaurantsPage", "Header")
        assert "padding" in result or "16px" in result

    def test_section_with_component_refs_listed(self):
        d = self._d()
        r, _ = d.pick_reader(doc="doc", active_doc="")
        result = d.get_section(r, "RestaurantsPage", "Header")
        assert "BtnPrimary" in result

    def test_section_with_texts_included(self):
        d = self._d()
        r, _ = d.pick_reader(doc="doc", active_doc="")
        result = d.get_section(r, "RestaurantsPage", "Header")
        assert "Restaurantes" in result

    def test_section_with_jsx_snippet_included(self):
        d = self._d()
        r, _ = d.pick_reader(doc="doc", active_doc="")
        result = d.get_section(r, "RestaurantsPage", "Header")
        assert "header jsx" in result

    def test_section_not_found_returns_graceful_message(self):
        d = self._d()
        r, _ = d.pick_reader(doc="doc", active_doc="")
        result = d.get_section(r, "RestaurantsPage", "FooterXXX999")
        assert "FooterXXX999" in result or "não encontrad" in result.lower()


# ── get_component: rich rendering ────────────────────────────────────────────

class TestGetComponentRichRendering:
    def _d(self):
        return ToolDispatcher([("doc", RichMockReader())])

    def test_component_with_styles_shows_state_groups(self):
        d = self._d()
        r, _ = d.pick_reader(doc="doc", active_doc="")
        result = d.get_component(r, "BtnWithStyles")
        assert "default" in result or "hover" in result

    def test_component_with_tokens_listed(self):
        d = self._d()
        r, _ = d.pick_reader(doc="doc", active_doc="")
        result = d.get_component(r, "BtnWithStyles")
        assert "primary" in result

    def test_component_with_children_listed(self):
        d = self._d()
        r, _ = d.pick_reader(doc="doc", active_doc="")
        result = d.get_component(r, "BtnWithStyles")
        assert "Badge" in result

    def test_component_with_jsx_snippet_rendered(self):
        d = self._d()
        r, _ = d.pick_reader(doc="doc", active_doc="")
        result = d.get_component(r, "BtnWithStyles")
        assert "button" in result.lower()


# ── find_token_usage ──────────────────────────────────────────────────────────

class TestFindTokenUsageTool:
    def _d(self):
        return ToolDispatcher([("doc", RichMockReader())])

    def test_found_token_includes_value(self):
        d = self._d()
        r, _ = d.pick_reader(doc="doc", active_doc="")
        result = d.find_token_usage(r, "#ffb81c")
        assert "#ffb81c" in result

    def test_found_token_includes_components(self):
        d = self._d()
        r, _ = d.pick_reader(doc="doc", active_doc="")
        result = d.find_token_usage(r, "#ffb81c")
        assert "BtnPrimary" in result

    def test_found_token_includes_screens(self):
        d = self._d()
        r, _ = d.pick_reader(doc="doc", active_doc="")
        result = d.find_token_usage(r, "#ffb81c")
        assert "RestaurantsPage" in result

    def test_not_found_returns_graceful_message(self):
        d = self._d()
        r, _ = d.pick_reader(doc="doc", active_doc="")
        result = d.find_token_usage(r, "zzz_unknown_token")
        assert "zzz_unknown_token" in result or "não encontrado" in result.lower()


# ── impact: component and token paths ────────────────────────────────────────

class TestImpactTool:
    def _d(self):
        return ToolDispatcher([("doc", RichMockReader())])

    def test_component_impact_shows_type(self):
        d = self._d()
        r, _ = d.pick_reader(doc="doc", active_doc="")
        result = d.impact(r, "BtnPrimary")
        assert "button" in result

    def test_component_impact_shows_affected_screens(self):
        d = self._d()
        r, _ = d.pick_reader(doc="doc", active_doc="")
        result = d.impact(r, "BtnPrimary")
        assert "RestaurantsPage" in result

    def test_token_impact_shows_label_and_value(self):
        d = self._d()
        r, _ = d.pick_reader(doc="doc", active_doc="")
        result = d.impact(r, "primary")
        assert "primary" in result
        assert "#ffb81c" in result

    def test_token_impact_shows_using_components(self):
        d = self._d()
        r, _ = d.pick_reader(doc="doc", active_doc="")
        result = d.impact(r, "primary")
        assert "BtnPrimary" in result

    def test_not_found_returns_graceful_message(self):
        d = self._d()
        r, _ = d.pick_reader(doc="doc", active_doc="")
        result = d.impact(r, "totally_unknown_xyz")
        assert "não encontrado" in result.lower() or "totally_unknown" in result


# ── get_full_jsx ──────────────────────────────────────────────────────────────

class TestGetFullJsxTool:
    def _d(self):
        return ToolDispatcher([("doc", RichMockReader())])

    def test_found_jsx_renders_code_block(self):
        d = self._d()
        r, _ = d.pick_reader(doc="doc", active_doc="")
        result = d.get_full_jsx(r, "BtnPrimary")
        assert "```jsx" in result
        assert "button" in result

    def test_not_found_returns_helpful_message(self):
        d = self._d()
        r, _ = d.pick_reader(doc="doc", active_doc="")
        result = d.get_full_jsx(r, "ComponentWithNoJSX")
        assert "force" in result.lower() or "disponível" in result.lower()

    def test_clean_jsx_keeps_complete_header_unflagged(self):
        # No marker survived sanitize_jsx for this snippet — must not carry
        # a false-positive "this was cut" warning.
        d = self._d()
        r, _ = d.pick_reader(doc="doc", active_doc="")
        result = d.get_full_jsx(r, "BtnPrimary")
        assert "sanitizado" not in result.lower()

    def test_sanitized_jsx_carries_explicit_warning(self):
        # The stored snippet already went through sanitize_jsx at
        # extraction time — a caller must be told this isn't the original
        # source, instead of reading "JSX completo" and stopping there.
        d = self._d()
        r, _ = d.pick_reader(doc="doc", active_doc="")
        result = d.get_full_jsx(r, "BasicTab")
        assert "sanitizado" in result.lower()
        assert "{[conditional:Chip]}" in result


# ── get_component_interactions ────────────────────────────────────────────────

class TestGetComponentInteractionsTool:
    def _d(self):
        return ToolDispatcher([("doc", RichMockReader())])

    def test_component_with_interactions_rendered(self):
        d = self._d()
        r, _ = d.pick_reader(doc="doc", active_doc="")
        result = d.get_component_interactions(r, "BtnHover")
        assert "HOVER" in result or "hover" in result
        assert "backgroundColor" in result

    def test_from_and_to_values_shown(self):
        d = self._d()
        r, _ = d.pick_reader(doc="doc", active_doc="")
        result = d.get_component_interactions(r, "BtnHover")
        assert "#ffb81c" in result
        assert "#f59e0b" in result

    def test_transition_shown(self):
        d = self._d()
        r, _ = d.pick_reader(doc="doc", active_doc="")
        result = d.get_component_interactions(r, "BtnHover")
        assert "0.2s" in result

    def test_no_interactions_returns_graceful_message(self):
        d = self._d()
        r, _ = d.pick_reader(doc="doc", active_doc="")
        result = d.get_component_interactions(r, "SectionCard")
        assert "nenhuma" in result.lower() or "não detectada" in result.lower()


# ── _find_reader substring match ─────────────────────────────────────────────

class TestFindReaderSubstringMatch:
    def test_substring_finds_reader(self):
        d = ToolDispatcher([("ipede-v7", RichMockReader()), ("admin", RichMockReader())])
        reader, err = d.pick_reader(doc="ipede", active_doc="")
        assert reader is not None
        assert err is None

    def test_exact_beats_substring(self):
        d = ToolDispatcher([("app", RichMockReader()), ("myapp", RichMockReader())])
        reader, err = d.pick_reader(doc="app", active_doc="")
        assert reader is not None

    def test_malformed_doc_name_falls_through_to_not_found(self):
        # C27/T52: a doc name that GraphDocumentName would reject (path
        # traversal shape) must not raise — it resolves to the same
        # friendly "not found" message as any other unmatched name.
        d = ToolDispatcher([("ipede-v7", RichMockReader())])
        reader, err = d.pick_reader(doc="../etc/passwd", active_doc="")
        assert reader is None
        assert "not found" in err.lower()


# ── Truncation warnings: agent must know when data was cut ────────────────────

class _OverflowReader:
    """Returns more items than the display limits in every collection."""

    _TEXTS_9  = [f"Text item {i}" for i in range(9)]
    _STYLES_9_BY_ELEMENT = {
        "(estilo da seção)": [{"property": f"prop{i}", "value": f"val{i}"} for i in range(9)],
    }
    _TEXTS_16 = [{"t.content": f"Word {i}", "t.text_type": "label", "t.element": "span"}
                 for i in range(16)]
    _STYLES_15_BY_STATE = {
        "default": [{"property": f"prop{i}", "value": f"val{i}"} for i in range(15)]
    }

    def list_screens(self): return []
    def get_tokens(self, category=None): return []
    def list_components(self, comp_type=None): return []
    def count_nodes(self): return {}
    def get_impact(self, n): return {"found": False}

    def get_section(self, screen, section_hint):
        return {
            "id": "sec_x", "name": "BigSection", "detection_method": "comment",
            "styles_by_element": self._STYLES_9_BY_ELEMENT,
            "component_refs": ["BtnPrimary"],
            "texts": self._TEXTS_9,
            "jsx_snippet": "",
        }

    def get_component_spec(self, name):
        return {
            "c.name": "OverflowComp", "c.comp_type": "card",
            "c.occurrence": 3, "c.jsx_snippet": "",
            "c.classes": "",
            "styles_by_state": self._STYLES_15_BY_STATE,
            "tokens": [],
            "texts":  self._TEXTS_16,
            "interactions": [],
            "children": [],
            "parents":  [],
            "screens_using": [],
        }


class TestTruncationWarnings:
    """When output is capped, the agent must receive a visible '+N more' notice."""

    def _dispatcher(self):
        return ToolDispatcher([("proto", _OverflowReader())])

    def test_section_styles_truncation_warning(self):
        d = self._dispatcher()
        result = d.dispatch("get_section", {"screen": "X", "section": "BigSection"}, "")
        # 9 styles, limit 6 → must mention remaining count
        assert "+" in result and "mais" in result.lower(), (
            "Expected truncation notice '+N mais' in section styles output"
        )

    def test_section_texts_truncation_warning(self):
        d = self._dispatcher()
        result = d.dispatch("get_section", {"screen": "X", "section": "BigSection"}, "")
        # 9 texts, limit 8 → must mention remaining count
        assert "+" in result and "mais" in result.lower(), (
            "Expected truncation notice '+N mais' in section texts output"
        )

    def test_spec_styles_truncation_warning(self):
        d = self._dispatcher()
        result = d.dispatch("get_component_spec", {"name": "OverflowComp"}, "")
        # 15 styles in 'default' state, limit 12 → must mention remaining count
        assert "+" in result and "mais" in result.lower(), (
            "Expected truncation notice '+N mais' in component spec styles output"
        )

    def test_spec_texts_truncation_warning(self):
        d = self._dispatcher()
        result = d.dispatch("get_component_spec", {"name": "OverflowComp"}, "")
        # 16 texts, limit 8 → must mention remaining count
        assert "+" in result and "mais" in result.lower(), (
            "Expected truncation notice '+N mais' in component spec texts output"
        )

    def test_no_warning_when_within_limit(self):
        """No spurious warning when data fits within the cap."""
        class SmallReader(_OverflowReader):
            def get_section(self, screen, section_hint):
                return {
                    "id": "s", "name": "Small", "detection_method": "comment",
                    "styles_by_element": {"(estilo da seção)": [{"property": "padding", "value": "4px"}]},
                    "component_refs": [], "texts": ["Hello"], "jsx_snippet": "",
                }
        d = ToolDispatcher([("proto", SmallReader())])
        result = d.dispatch("get_section", {"screen": "X", "section": "Small"}, "")
        assert "mais" not in result.lower()


# ── truncated_fields: agent must know a cap was hit, not just a short list ───
# ── (C28/T57 — distinct from _truncation_notice, which is about display-time ─
# ── slicing; this is about extraction-time caps like MAX_STYLES_PER_COMPONENT) ─

class _CappedExtractionReader:
    def get_component(self, name):
        return {
            "c.name": "CappedComp", "c.comp_type": "card", "c.jsx_snippet": "<div/>",
            "c.occurrence": 1, "c.classes": "", "c.truncated_fields": "styles,texts",
            "styles": [], "tokens": [], "texts": [], "interactions": [],
            "screens_using": [], "children": [],
        }

    def get_component_spec(self, name):
        return {
            "c.name": "CappedComp", "c.comp_type": "card", "c.jsx_snippet": "",
            "c.occurrence": 1, "c.classes": "", "c.truncated_fields": "interactions",
            "styles_by_state": {}, "tokens": [], "texts": [], "interactions": [],
            "children": [], "parents": [], "screens_using": [],
        }

    def get_screen_full(self, name):
        return {
            "name": "CappedScreen", "component_count": 1, "sections_count": 0,
            "sections": [],
            "components": [{
                "name": "CappedComp", "comp_type": "card", "occurrence": 1,
                "jsx_snippet": "", "classes": "", "truncated_fields": ["classes"],
                "styles_by_state": {}, "tokens": [], "texts": [],
                "interactions": [], "props": [], "children": [],
            }],
        }


class _ManyComponentsReader:
    """150 components — more than the default list_components page size."""

    def list_components(self, comp_type=None):
        return [
            {"c.name": f"Comp{i:03d}", "c.comp_type": "card", "c.occurrence": 150 - i}
            for i in range(150)
        ]


class TestListComponentsPagination:
    def _dispatcher(self):
        return ToolDispatcher([("proto", _ManyComponentsReader())])

    def test_default_page_capped_at_100(self):
        result = self._dispatcher().dispatch("list_components", {}, "")
        shown = result.count("| Comp")
        assert shown == 100

    def test_default_page_shows_truncation_notice(self):
        result = self._dispatcher().dispatch("list_components", {}, "")
        assert "+50" in result and "limit=" in result

    def test_explicit_limit_overrides_default(self):
        result = self._dispatcher().dispatch("list_components", {"limit": 10}, "")
        assert result.count("| Comp") == 10
        assert "+140" in result

    def test_limit_larger_than_total_shows_everything_without_notice(self):
        result = self._dispatcher().dispatch("list_components", {"limit": 500}, "")
        assert result.count("| Comp") == 150
        assert "mais" not in result.lower()

    def test_most_occurring_components_shown_first(self):
        # reader.list_components is already sorted by occurrence DESC —
        # the shown page must be the most-used components, not an arbitrary cut.
        result = self._dispatcher().dispatch("list_components", {"limit": 3}, "")
        assert "Comp000" in result
        assert "Comp099" not in result


class _BuildDiffReader:
    def __init__(self, diff):
        self._diff = diff

    def get_build_diff(self):
        return self._diff


class TestGetBuildDiffTool:
    def test_tool_in_definitions(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "get_build_diff" in names

    def test_no_state_path_reports_unavailable(self):
        d = ToolDispatcher([("proto", _BuildDiffReader(None))])
        result = d.dispatch("get_build_diff", {}, "")
        assert "Nenhum diff" in result

    def test_first_build_reports_no_prior_build(self):
        d = ToolDispatcher([("proto", _BuildDiffReader({
            "is_first_build": True, "screens_added": [], "screens_removed": [],
            "comps_added": [], "comps_removed": [],
        }))])
        result = d.dispatch("get_build_diff", {}, "")
        assert "Primeira build" in result

    def test_no_changes_reports_nothing_changed(self):
        d = ToolDispatcher([("proto", _BuildDiffReader({
            "is_first_build": False, "screens_added": [], "screens_removed": [],
            "comps_added": [], "comps_removed": [],
        }))])
        result = d.dispatch("get_build_diff", {}, "")
        assert "Nenhuma mudança" in result

    def test_real_diff_lists_all_four_categories(self):
        d = ToolDispatcher([("proto", _BuildDiffReader({
            "is_first_build": False,
            "screens_added": ["NewPage"], "screens_removed": ["OldPage"],
            "comps_added": ["NewBtn"], "comps_removed": ["OldBtn"],
        }))])
        result = d.dispatch("get_build_diff", {}, "")
        assert "NewPage" in result and "OldPage" in result
        assert "NewBtn" in result and "OldBtn" in result


class TestTruncatedFieldsNoticeHelper:
    def test_none_returns_none(self):
        assert _truncated_fields_notice(None) is None

    def test_empty_string_returns_none(self):
        assert _truncated_fields_notice("") is None

    def test_empty_list_returns_none(self):
        assert _truncated_fields_notice([]) is None

    def test_string_input_lists_fields(self):
        notice = _truncated_fields_notice("styles,texts")
        assert "styles" in notice and "texts" in notice

    def test_list_input_lists_fields(self):
        notice = _truncated_fields_notice(["classes"])
        assert "classes" in notice

    def test_recoverable_via_suggests_get_full_jsx(self):
        notice = _truncated_fields_notice("styles", recoverable_via="MyComp")
        assert "get_full_jsx('MyComp')" in notice

    def test_no_recoverable_via_omits_suggestion(self):
        notice = _truncated_fields_notice("styles")
        assert "get_full_jsx" not in notice


class TestTruncatedFieldsNotice:
    def _dispatcher(self):
        return ToolDispatcher([("proto", _CappedExtractionReader())])

    def test_get_component_shows_truncated_fields(self):
        result = self._dispatcher().dispatch("get_component", {"name": "CappedComp"}, "")
        assert "styles" in result and "texts" in result
        assert "get_full_jsx" in result

    def test_get_component_spec_shows_truncated_fields(self):
        result = self._dispatcher().dispatch("get_component_spec", {"name": "CappedComp"}, "")
        assert "interactions" in result
        assert "get_full_jsx" in result

    def test_get_screen_full_shows_truncated_fields(self):
        result = self._dispatcher().dispatch("get_screen_full", {"name": "CappedScreen"}, "")
        assert "classes" in result
        assert "get_full_jsx" in result

    def test_no_notice_when_nothing_truncated(self):
        class CleanReader(_CappedExtractionReader):
            def get_component(self, name):
                d = super().get_component(name)
                d["c.truncated_fields"] = ""
                return d
        result = ToolDispatcher([("proto", CleanReader())]).dispatch(
            "get_component", {"name": "CappedComp"}, ""
        )
        assert "Extração truncada" not in result


# ── JSX truncation: agent must know a snippet was cut, and whether it can ────
# ── recover the rest via get_full_jsx (components only, not sections) ───────

class _JsxOverflowReader:
    """jsx_snippet longer than every render-time cap (2000/2500/3000/4000)."""

    _LONG_JSX = "<div>" + "x" * 4100 + "</div>"

    def get_section(self, screen, section_hint):
        return {
            "id": "sec_x", "name": "BigSection", "detection_method": "comment",
            "styles_by_element": {}, "component_refs": [], "texts": [],
            "jsx_snippet": self._LONG_JSX,
        }

    def get_screen_full(self, name):
        return {
            "name": "BigScreen", "component_count": 1, "sections_count": 1,
            "sections": [{
                "name": "BigSection", "detection_method": "comment",
                "styles_by_element": {}, "component_refs": [], "texts": [],
                "jsx_snippet": self._LONG_JSX,
            }],
            "components": [{
                "name": "BigComp", "comp_type": "card", "occurrence": 1,
                "jsx_snippet": self._LONG_JSX, "classes": "",
                "styles_by_state": {}, "tokens": [], "texts": [],
                "interactions": [], "props": [], "children": [],
            }],
        }

    def get_component(self, name):
        return {
            "c.name": "BigComp", "c.comp_type": "card", "c.occurrence": 1,
            "c.jsx_snippet": self._LONG_JSX, "c.classes": "",
            "styles": [], "tokens": [], "texts": [], "interactions": [],
            "screens_using": [], "children": [],
        }

    def get_component_children(self, name): return []
    def find_screens_using_comp_transitively(self, name): return []


class TestJsxTruncationWarnings:
    """A capped JSX snippet must say so — and must only point to get_full_jsx
    where that tool can actually recover the rest (Component nodes; sections
    have no such lookup)."""

    def _dispatcher(self):
        return ToolDispatcher([("proto", _JsxOverflowReader())])

    def test_get_component_notice_is_visible_and_actionable(self):
        result = self._dispatcher().dispatch("get_component", {"name": "BigComp"}, "proto")
        assert "+" in result
        assert "get_full_jsx('BigComp')" in result

    def test_get_section_notice_is_visible_without_a_false_lead(self):
        result = self._dispatcher().dispatch(
            "get_section", {"screen": "X", "section": "BigSection"}, "proto"
        )
        assert "+" in result
        assert "get_full_jsx" not in result

    def test_get_screen_full_component_notice_is_actionable(self):
        result = self._dispatcher().dispatch("get_screen_full", {"name": "BigScreen"}, "proto")
        assert "get_full_jsx('BigComp')" in result

    def test_get_screen_full_section_notice_has_no_false_lead(self):
        result = self._dispatcher().dispatch("get_screen_full", {"name": "BigScreen"}, "proto")
        # Only the component-level cut may reference get_full_jsx; the
        # section-level cut must not carry the same (false) claim.
        assert result.count("get_full_jsx") == 1
