"""
A component's Styles section renders nothing at all when no Style rows were
extracted for it — RestaurantAvatar (from the reference prototype) is the
concrete case: its JSX has a full `style={{...}}` block (width, background,
border, color — nine properties), but every value is a runtime expression
(`hsl(${hue}, 35%, 28%)`, a bare `size` variable, a `small ? 11 : 13`
ternary), so none reduce to a literal the extractor can store as a Style
row. An empty Styles section then looks identical to "this component
genuinely has no styling." StyleExtractionGap tells the two apart and,
when they collide, points the reader back at the JSX instead of letting
the gap pass in silence.
"""

from __future__ import annotations

from design_graph.mcp.tools import StyleExtractionGap

DYNAMIC_STYLE_JSX = (
    "<div style={{ width: size, background: `hsl(${hue}, 35%, 28%)`, "
    "fontSize: small ? 11 : 13 }}>{initials}</div>"
)


class TestStyleExtractionGap:
    def test_no_inline_style_attribute_means_no_gap(self):
        gap = StyleExtractionGap("<span>{initials}</span>")
        assert gap.exists is False
        assert gap.notice() is None

    def test_inline_style_attribute_means_a_gap(self):
        assert StyleExtractionGap(DYNAMIC_STYLE_JSX).exists is True

    def test_notice_is_none_when_there_is_no_gap(self):
        assert StyleExtractionGap("<span/>").notice() is None

    def test_notice_explains_the_gap_when_present(self):
        notice = StyleExtractionGap(DYNAMIC_STYLE_JSX).notice()
        assert notice is not None
        assert "JSX" in notice

    def test_empty_jsx_means_no_gap(self):
        assert StyleExtractionGap("").exists is False
