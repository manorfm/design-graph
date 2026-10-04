"""
A component's Styles section renders nothing at all when no Style rows were
extracted for it — RestaurantAvatar (from the reference prototype) is the
concrete case: its JSX has a full `style={{...}}` block (width, background,
border, color — nine properties), but every value is a runtime expression
(`hsl(${hue}, 35%, 28%)`, a bare `size` variable, a `small ? 11 : 13`
ternary), so none reduce to a literal the extractor can store as a Style
row. An empty Styles section then looks identical to "this component
genuinely has no styling." The capture records whether the source declares
inline styling; StyleExtractionGap turns that fact into a notice pointing
the reader back at the source instead of letting the gap pass in silence.
"""

from __future__ import annotations

from design_graph.interface.mcp.notices import StyleExtractionGap


class TestStyleExtractionGap:
    """The capture states whether a source declares inline styling; the gap is that fact alone."""

    def test_source_without_inline_styling_has_no_gap(self):
        gap = StyleExtractionGap(declares_inline_styles=False)
        assert gap.exists is False
        assert gap.notice() is None

    def test_source_declaring_inline_styling_has_a_gap(self):
        assert StyleExtractionGap(declares_inline_styles=True).exists is True

    def test_notice_explains_the_gap_when_present(self):
        assert StyleExtractionGap(declares_inline_styles=True).notice() is not None
