"""
All three tools that render a Styles section (get_component, get_screen_full,
get_component_spec) must warn when the section is empty but the component's
own JSX visibly declares inline styles — otherwise an agent reading only the
structured section concludes "no styling" for a component whose look is
entirely runtime-computed (RestaurantAvatar's avatar-color hashing is the
reference case). One StyleExtractionGap check reused at all three sites
means the fix (and this coverage) only has to exist once.
"""

from __future__ import annotations

from design_graph.mcp.tools import ToolDispatcher

DYNAMIC_STYLE_JSX = (
    "<div style={{ width: size, background: `hsl(${hue}, 35%, 28%)` }}>{initials}</div>"
)


class _DynamicStyleReader:
    """One component with inline styles that produced zero Style rows."""

    def get_component(self, name):
        return {
            "c.name": "RestaurantAvatar", "c.comp_type": "component", "c.occurrence": 1,
            "c.jsx_snippet": DYNAMIC_STYLE_JSX, "c.classes": "",
            "styles": [], "tokens": [], "texts": [], "interactions": [],
            "screens_using": [], "children": [],
        }

    def get_screen_full(self, name):
        return {
            "name": "Screen", "component_count": 1, "sections_count": 0,
            "sections": [],
            "components": [{
                "name": "RestaurantAvatar", "comp_type": "component", "occurrence": 1,
                "jsx_snippet": DYNAMIC_STYLE_JSX, "classes": "",
                "styles_by_state": {}, "tokens": [], "texts": [],
                "interactions": [], "props": [], "children": [],
            }],
        }

    def get_component_spec(self, name):
        return {
            "c.name": "RestaurantAvatar", "c.comp_type": "component", "c.occurrence": 1,
            "c.jsx_snippet": DYNAMIC_STYLE_JSX, "c.classes": "",
            "screens_using": [], "parents": [], "children": [],
            "styles_by_state": {}, "tokens": [], "texts": [], "interactions": [], "props": [],
        }


class _NoStyleAtAllReader(_DynamicStyleReader):
    """Same shape, but the JSX has no inline style attribute at all — the
    honest "no styling" case, which must stay silent (no false gap notice)."""

    def get_component(self, name):
        d = super().get_component(name)
        d["c.jsx_snippet"] = "<span>{initials}</span>"
        return d

    def get_screen_full(self, name):
        d = super().get_screen_full(name)
        d["components"][0]["jsx_snippet"] = "<span>{initials}</span>"
        return d

    def get_component_spec(self, name):
        d = super().get_component_spec(name)
        d["c.jsx_snippet"] = "<span>{initials}</span>"
        return d


class TestStyleGapNoticeAppearsAcrossAllRenderSites:
    def _dispatcher(self, reader):
        return ToolDispatcher([("proto", reader())])

    def test_get_component_warns_on_dynamic_only_styles(self):
        out = self._dispatcher(_DynamicStyleReader).dispatch(
            "get_component", {"name": "RestaurantAvatar"}, "proto"
        )
        assert "JSX" in out and "runtime" in out.lower()

    def test_get_screen_full_warns_on_dynamic_only_styles(self):
        out = self._dispatcher(_DynamicStyleReader).dispatch(
            "get_screen_full", {"name": "Screen"}, "proto"
        )
        assert "runtime" in out.lower()

    def test_get_component_spec_warns_on_dynamic_only_styles(self):
        out = self._dispatcher(_DynamicStyleReader).dispatch(
            "get_component_spec", {"name": "RestaurantAvatar"}, "proto"
        )
        assert "runtime" in out.lower()

    def test_get_component_stays_silent_when_genuinely_unstyled(self):
        out = self._dispatcher(_NoStyleAtAllReader).dispatch(
            "get_component", {"name": "RestaurantAvatar"}, "proto"
        )
        assert "runtime" not in out.lower()

    def test_get_screen_full_stays_silent_when_genuinely_unstyled(self):
        out = self._dispatcher(_NoStyleAtAllReader).dispatch(
            "get_screen_full", {"name": "Screen"}, "proto"
        )
        assert "runtime" not in out.lower()

    def test_get_component_spec_stays_silent_when_genuinely_unstyled(self):
        out = self._dispatcher(_NoStyleAtAllReader).dispatch(
            "get_component_spec", {"name": "RestaurantAvatar"}, "proto"
        )
        assert "runtime" not in out.lower()
