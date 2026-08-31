"""
get_screen_full must warn when a screen produced zero Sections and zero
Components even though its own JSX is non-trivial — otherwise an agent
reading a "Components: 0 | Sections: 0" heading has no way to tell "this
screen genuinely renders nothing of its own" apart from "the extraction
cascade found no comment marker, no padding-styled div and no raw-markup
list to anchor a Section on, and its content is silently unreachable here".

Real case: HistoryView (toToggle prototype) used to report exactly this
before section_extractor gained its inline-list fallback — get_full_jsx
could still recover the real markup, but get_screen_full gave no hint that
anything was missing. One StyleExtractionGap-shaped check, mirroring the
existing pattern for the same class of problem (get_component/
get_screen_full/get_component_spec already share one for styles).
"""

from __future__ import annotations

from design_graph.mcp.tools import ToolDispatcher

_SUBSTANTIAL_JSX = (
    '<div className="audit"><div className="audit-item">'
    '<span className="audit-text">Some real content that is definitely '
    "longer than the short-circuit threshold used to decide whether this "
    "screen's own markup is worth warning about at all.</span></div></div>"
)


class _NothingDecomposedReader:
    """A screen with real JSX but zero Sections and zero Components."""

    def get_screen_full(self, name):
        return {
            "name": "HistoryView", "component_count": 0, "sections_count": 0,
            "jsx_snippet": _SUBSTANTIAL_JSX,
            "sections": [], "components": [],
        }


class _TrivialScreenReader:
    """A screen that genuinely has nothing — must stay silent."""

    def get_screen_full(self, name):
        return {
            "name": "EmptyScreen", "component_count": 0, "sections_count": 0,
            "jsx_snippet": "<div />",
            "sections": [], "components": [],
        }


class _DecomposedScreenReader:
    """A screen with real Sections — must stay silent regardless of jsx length."""

    def get_screen_full(self, name):
        return {
            "name": "NormalScreen", "component_count": 0, "sections_count": 1,
            "jsx_snippet": _SUBSTANTIAL_JSX,
            "sections": [{
                "id": "s1", "name": "Hero", "detection_method": "comment",
                "styles": {}, "component_refs": [], "texts": [], "jsx_snippet": "",
            }],
            "components": [],
        }


class TestScreenStructureGapNotice:
    def _dispatcher(self, reader):
        return ToolDispatcher([("proto", reader())])

    def test_warns_when_nothing_decomposed_but_jsx_is_substantial(self):
        out = self._dispatcher(_NothingDecomposedReader).dispatch(
            "get_screen_full", {"name": "HistoryView"}, "proto"
        )
        assert "get_full_jsx" in out
        assert "HistoryView" in out

    def test_stays_silent_when_screen_genuinely_has_nothing(self):
        out = self._dispatcher(_TrivialScreenReader).dispatch(
            "get_screen_full", {"name": "EmptyScreen"}, "proto"
        )
        assert "get_full_jsx" not in out

    def test_stays_silent_when_sections_were_found(self):
        out = self._dispatcher(_DecomposedScreenReader).dispatch(
            "get_screen_full", {"name": "NormalScreen"}, "proto"
        )
        assert "get_full_jsx" not in out
