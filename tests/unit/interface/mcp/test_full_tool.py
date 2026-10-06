"""
get_full is the one way back to whatever another answer shortened — a source
in parts, a style or text list, a component's data — and every notice points
to it the same way.
"""

import pytest

from design_graph.interface.mcp.notices import full_call
from design_graph.interface.mcp.tools import ToolDispatcher


@pytest.mark.parametrize("target,aspect,expected", [
    ("Card", "styles", 'get_full(name="Card", aspect="styles")'),
    ('screen="Home", section="Lista"', "texts", 'get_full(screen="Home", section="Lista", aspect="texts")'),
    ("Card", "source", 'get_full(name="Card", aspect="source")'),
])
def test_every_notice_names_the_same_call(target, aspect, expected):
    assert full_call(aspect, target) == expected


class _Reader:
    def get_full_source(self, name):
        return {"source_code": "<div>oi</div>", "source_lang": "html"} if name == "Card" else None


def test_the_dispatcher_routes_each_aspect():
    tools = ToolDispatcher([("doc", _Reader())])
    assert "<div>oi</div>" in tools.dispatch("get_full", {"name": "Card", "aspect": "source"}, "doc")
    assert "aspect" in tools.dispatch("get_full", {"name": "Card", "aspect": "cores"}, "doc")


def test_the_old_tools_are_gone():
    from design_graph.interface.mcp.tool_definitions import TOOL_DEFINITIONS

    names = {tool["name"] for tool in TOOL_DEFINITIONS}
    assert "get_full" in names
    assert not names & {"get_full_source", "get_full_styles", "get_full_texts", "get_component_data"}
