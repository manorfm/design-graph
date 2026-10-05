"""A component lists each token with its mode, the way get_tokens does — `--sunk` twice reads as light and dark, not as a contradiction."""

from design_graph.interface.mcp.component_tools import get_component, get_component_spec
from design_graph.interface.mcp.markdown import component_lines

_SUNK = [
    {"t.label": "--sunk", "t.value": "#F4F1EA", "t.category": "css_var", "t.mode": "claro"},
    {"t.label": "--sunk", "t.value": "#1C1B19", "t.category": "css_var", "t.mode": "escuro"},
    {"t.label": "space_16", "t.value": "16px", "t.category": "spacing", "t.mode": ""},
]


class _Reader:
    def resolve_named_entity(self, name):
        return ("component", name)

    def get_component(self, name):
        return {"c.name": name, "c.comp_type": "component", "c.occurrence": 1, "styles": [],
                "tokens": _SUNK, "texts": [], "interactions": [], "children": []}

    def get_component_spec(self, name):
        return {"c.name": name, "c.comp_type": "component", "c.occurrence": 1, "styles_by_state": {},
                "responsive_styles_by_media": {}, "tokens": _SUNK, "texts": [], "interactions": [],
                "props": [], "children": []}


def test_get_component_shows_each_token_mode():
    out = get_component(_Reader(), "Sidebar")
    assert "- **--sunk** [claro] = `#F4F1EA` (css_var)" in out
    assert "- **--sunk** [escuro] = `#1C1B19` (css_var)" in out
    assert "- **space_16** = `16px` (spacing)" in out


def test_get_component_spec_shows_each_token_mode():
    out = get_component_spec(_Reader(), "Sidebar")
    assert "| --sunk [claro] | #F4F1EA | css_var |" in out
    assert "| space_16 | 16px | spacing |" in out


def test_component_inside_a_tree_shows_each_token_mode():
    comp = {"name": "Sidebar", "comp_type": "component", "occurrence": 1, "children": [], "props": [],
            "styles_by_state": {}, "declares_inline_styles": False, "referenced_data": {}, "tokens": [{"label": t["t.label"], "value": t["t.value"], "category": t["t.category"],
                                      "mode": t["t.mode"]} for t in _SUNK],
            "interactions": [], "texts": [], "source_code": "", "source_lang": ""}
    out = "\n".join(component_lines(comp, heading="### Sidebar"))
    assert "- **--sunk** [escuro] = `#1C1B19` (css_var)" in out
    assert "- **space_16** = `16px` (spacing)" in out
