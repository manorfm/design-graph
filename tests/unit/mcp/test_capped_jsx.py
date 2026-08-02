"""
JSX snippets get capped before rendering in get_component, get_screen_full and
get_section (4000/2500/2000/3000 chars) to keep MCP responses small. Slicing
the string directly, the way every one of those call sites used to, gives no
signal that content is missing — an agent reconstructing a screen from a
silently incomplete component never finds out. CappedJsx ties the cut fact to
the value itself, the same way PropDefault (core/models.py) ties "is
required" to a default-value string, so every render site gets the same
notice for free instead of re-deriving it from a raw length comparison.
"""

from __future__ import annotations

from design_graph.mcp.tools import CappedJsx


class TestCappedJsx:
    def test_short_text_is_not_cut(self):
        jsx = CappedJsx("<div/>", limit=100)
        assert jsx.was_cut is False

    def test_long_text_is_sliced_to_the_limit(self):
        jsx = CappedJsx("x" * 150, limit=100)
        assert len(jsx) == 100
        assert jsx.was_cut is True

    def test_text_exactly_at_limit_is_not_cut(self):
        jsx = CappedJsx("x" * 100, limit=100)
        assert jsx.was_cut is False

    def test_behaves_as_a_plain_string(self):
        jsx = CappedJsx("<div>hi</div>", limit=100)
        assert jsx == "<div>hi</div>"
        assert "hi" in jsx


class TestCappedJsxNotice:
    def test_none_when_not_cut(self):
        jsx = CappedJsx("<div/>", limit=100)
        assert jsx.notice(recoverable_via="Btn") is None

    def test_names_the_cut_amount(self):
        jsx = CappedJsx("x" * 150, limit=100)
        assert "+50" in jsx.notice(recoverable_via=None)

    def test_points_to_get_full_jsx_when_recoverable(self):
        jsx = CappedJsx("x" * 150, limit=100)
        assert "get_full_jsx('RestCard')" in jsx.notice(recoverable_via="RestCard")

    def test_no_false_recovery_lead_when_not_recoverable(self):
        """Sections have no get_full_jsx path — reader.get_full_jsx only
        matches Component nodes — so the notice must not claim one exists."""
        jsx = CappedJsx("x" * 150, limit=100)
        assert "get_full_jsx" not in jsx.notice(recoverable_via=None)
