"""
A section's own and class styles are listed; its nested elements' styles —
one per element, hundreds in a heatmap — are summed up in one line naming the
call that lists them all.
"""

from design_graph.interface.mcp.markdown import section_style_group_lines
from design_graph.model.graph.reader import SECTION_OWN_STYLES

_GROUPS = {
    SECTION_OWN_STYLES: [{"property": "padding", "value": "8px"}],
    ".card": [{"property": "gap", "value": "4px"}],
    "ul > li:1": [{"property": "color", "value": "red"}],
    "ul > li:2": [{"property": "color", "value": "blue"}],
    "ul > li:2 > span": [{"property": "font-size", "value": "38px"}],
}
_CALL = 'screen="Home", section="Lista"'


def test_own_and_class_styles_are_listed():
    out = "\n".join(section_style_group_lines(_GROUPS, recoverable_via=_CALL))
    assert "`padding`: `8px`" in out and "`gap`: `4px`" in out


def test_nested_elements_are_summed_up_with_the_call_that_lists_them():
    out = "\n".join(section_style_group_lines(_GROUPS, recoverable_via=_CALL))
    assert "38px" not in out and "ul > li" not in out
    assert f"3 elementos internos com estilo próprio — chame `get_full_styles({_CALL})`" in out


def test_no_summary_without_nested_elements():
    groups = {SECTION_OWN_STYLES: _GROUPS[SECTION_OWN_STYLES]}
    assert "elementos internos" not in "\n".join(section_style_group_lines(groups, recoverable_via=_CALL))
