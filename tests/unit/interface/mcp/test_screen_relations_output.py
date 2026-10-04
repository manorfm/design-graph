"""Screen responses tell where a screen leads, what it varies and the viewport it was designed for."""

from __future__ import annotations

from design_graph.interface.mcp.tools import ToolDispatcher

RELATIONS = {
    "viewport": {"width": 390, "height": 844},
    "navigates_to": [{"screen": "Perspective", "label": "Start"}],
    "navigated_from": [{"screen": "Conclusion", "label": "Restart"}],
    "variant_of": None,
    "variants": [{"screen": "Welcome (desktop)", "axis": "viewport"}],
}
NO_RELATIONS = {"viewport": None, "navigates_to": [], "navigated_from": [], "variant_of": None, "variants": []}


class _Reader:
    def __init__(self, relations):
        self.relations = relations

    def list_screens(self):
        return [
            {"name": "Welcome", "component_count": 1, "sections_count": 0, "top_components": [], "variant_of": ""},
            {"name": "Welcome (desktop)", "component_count": 1, "sections_count": 0, "top_components": [],
             "variant_of": "Welcome"},
        ]

    def get_screen(self, name):
        return {"name": "Welcome", "component_count": 0, "sections_count": 0,
                "components": [], "sections": [], "texts": [], "relations": self.relations}

    def get_screen_full(self, name):
        return {"name": "Welcome", "component_count": 0, "sections_count": 0, "source_code": "",
                "sections": [], "components": [], "layout_profiles": [], "relations": self.relations}


def _call(tool, relations=RELATIONS):
    return ToolDispatcher([("proto", _Reader(relations))]).dispatch(tool, {"name": "Welcome"}, "proto")


class TestScreenRelationsOutput:
    def test_screen_shows_viewport_navigation_and_variants(self):
        out = _call("get_screen")
        assert "**Viewport**: 390×844" in out
        assert "**Navega para**: Perspective («Start»)" in out
        assert "**Chega de**: Conclusion («Restart»)" in out
        assert "**Variantes**: Welcome (desktop) (viewport)" in out

    def test_screen_full_shows_the_same_relations(self):
        out = _call("get_screen_full")
        assert "**Viewport**: 390×844" in out
        assert "**Navega para**: Perspective («Start»)" in out

    def test_variant_names_its_base(self):
        relations = {**NO_RELATIONS, "variant_of": {"screen": "Welcome", "axis": "viewport"}}
        assert "**Variante de**: Welcome (viewport)" in _call("get_screen", relations)

    def test_screen_without_relations_adds_nothing(self):
        out = _call("get_screen", NO_RELATIONS)
        assert "Viewport" not in out and "Navega" not in out and "Variante" not in out

    def test_list_screens_marks_variants(self):
        out = ToolDispatcher([("proto", _Reader(RELATIONS))]).dispatch("list_screens", {}, "proto")
        assert "**Welcome (desktop)** (1 componentes) — variante de Welcome" in out
        assert "**Welcome** (1 componentes)\n" in out + "\n"
