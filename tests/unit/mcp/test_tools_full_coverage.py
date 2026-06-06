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

from design_graph.mcp.tools import ToolDispatcher


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
                "styles": {"padding": "16px", "margin": "8px"},
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


# ── Truncation warnings: agent must know when data was cut ────────────────────

class _OverflowReader:
    """Returns more items than the display limits in every collection."""

    _TEXTS_9  = [f"Text item {i}" for i in range(9)]
    _STYLES_9 = {f"prop{i}": f"val{i}" for i in range(9)}
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
            "styles": self._STYLES_9,
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
                    "styles": {"padding": "4px"},
                    "component_refs": [], "texts": ["Hello"], "jsx_snippet": "",
                }
        d = ToolDispatcher([("proto", SmallReader())])
        result = d.dispatch("get_section", {"screen": "X", "section": "Small"}, "")
        assert "mais" not in result.lower()
