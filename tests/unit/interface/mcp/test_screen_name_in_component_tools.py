"""
Asking a component tool about a screen answers as the screen — its own
source, the components it uses and where to get the whole page — instead
of "not found" (an agent cannot know beforehand that `App` is a screen).
"""

import pytest

from design_graph.interface.mcp.component_tools import get_component, get_component_full, get_component_spec
from design_graph.model.graph.reader import NamedEntity, NamedEntityResolution

_TOOLS = [get_component, get_component_spec, get_component_full]


class _Reader:
    """Knows one screen, `App`, using `Header` and `Footer`; no component by that name."""

    def resolve_named_entity(self, hint):
        if hint == "App":
            return NamedEntityResolution(entity=NamedEntity("screen", "App"))
        return NamedEntityResolution()

    def get_full_source(self, name):
        return {"source_code": "<main><Header/><Footer/></main>", "source_lang": "jsx", "source_simplified": False}

    def get_screen(self, name):
        return {"name": "App", "components": [{"c.name": "Header", "c.comp_type": "layout"},
                                             {"c.name": "Footer", "c.comp_type": "layout"}]}

    def get_component(self, name):
        return None

    get_component_spec = get_component_full = get_component

    def find_styles_by_class(self, name):
        return []


@pytest.mark.parametrize("tool", _TOOLS)
def test_screen_name_answers_as_the_screen(tool):
    out = tool(_Reader(), "App")
    assert "'App' é uma tela" in out
    assert "<main><Header/><Footer/></main>" in out
    assert "Header" in out and "Footer" in out
    assert "get_screen_full('App')" in out


@pytest.mark.parametrize("tool", _TOOLS)
def test_unknown_name_is_still_not_found(tool):
    assert "não encontrado" in tool(_Reader(), "Nada")
