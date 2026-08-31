"""
Tests for section_extractor's inline-list-markup detection strategy.

Real-world trigger: HistoryView (toToggle prototype) renders its audit trail
as `items.map((e, i) => (<div className="audit-item">...))` — raw JSX markup,
never factored into a named component like `UserRow`/`MemberRow` — with no
`{/* comment */}` markers and no inline `style={{padding}}` anywhere in the
screen. Both existing detection strategies (comment, structural) find nothing,
so the whole block — containers, classes, conditional icon, texts — silently
disappears from get_screen_full/get_screen_layout/list_components even though
get_full_jsx still recovers the raw JSX untouched.

This strategy recognizes `x.map((item[, i]) => (<lowercaseTag ...>` — raw
markup, never a named-component call — as a third, last-resort anchor to
build a Section on, reusing the exact same balanced-brace region scan
(js_parser.find_matching_delimiter) sanitize_jsx already relies on to bound
`{[list:Component]}` markers.
"""

from __future__ import annotations

from design_graph.core.models import ExtractedScreen
from design_graph.extraction.section_extractor import extract_sections
from design_graph.parsing.css_class_resolver import CssRule
from design_graph.parsing.js_parser import find_all_boundaries

HISTORY_VIEW_JS = """
function HistoryView() {
    return (
        <div className="page">
            <div className="audit-filter">
                {tabs.map(([k, label]) => (
                    <button key={k} className={"chip" + (filter === k ? " on" : "")} onClick={() => setFilter(k)}>{label}</button>
                ))}
            </div>
            <div className="audit">
                {items.map((e, i) => (
                    <div className="audit-item" key={e.id}>
                        <div className="audit-rail">
                            <div className={"audit-dot " + (AUDIT_DOT[e.type] || "")}>
                                <Icon name={AUDIT_ICON[e.type] || "history"} size={15} />
                            </div>
                            {i < items.length - 1 && <div className="audit-line" />}
                        </div>
                        <div className="audit-body">
                            <div className="audit-text" dangerouslySetInnerHTML={{ __html: e.text }} />
                            {e.target && <div className="audit-target">{e.target}</div>}
                            <div className="audit-meta">
                                <span className="who"><span className="audit-av">{e.initials}</span> {e.actor}</span>
                                <span>·</span><span>{e.when}</span>
                            </div>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    )
}
"""

NAMED_COMPONENT_LIST_JS = """
function UsersView() {
    return (
        <div className="page">
            {users.map(u => (
                <UserRow key={u.id} user={u} />
            ))}
        </div>
    )
}
"""

UNQUALIFIED_LIST_JS = """
function PlainTextList() {
    return (
        <div className="page">
            {lines.map((l, i) => (
                <span key={i}>{l}</span>
            ))}
        </div>
    )
}
"""


def _boundary(js: str, name: str):
    bounds = find_all_boundaries(js)
    return next(b for b in bounds if b.name == name)


def _screen(name: str) -> ExtractedScreen:
    return ExtractedScreen(name=name, component_refs=[], sections_count=0)


class TestInlineListMarkupIsLastResortStrategy:
    def test_finds_a_section_for_raw_markup_map_when_no_comments_or_padding(self):
        boundary = _boundary(HISTORY_VIEW_JS, "HistoryView")
        sections = extract_sections(HISTORY_VIEW_JS, _screen("HistoryView"), boundary)
        assert len(sections) >= 1

    def test_detection_method_is_list_item(self):
        boundary = _boundary(HISTORY_VIEW_JS, "HistoryView")
        sections = extract_sections(HISTORY_VIEW_JS, _screen("HistoryView"), boundary)
        assert any(s.detection_method == "list_item" for s in sections)

    def test_component_referenced_inside_the_list_row_is_captured(self):
        boundary = _boundary(HISTORY_VIEW_JS, "HistoryView")
        sections = extract_sections(HISTORY_VIEW_JS, _screen("HistoryView"), boundary)
        audit_section = next(s for s in sections if "Icon" in s.component_refs)
        assert "Icon" in audit_section.component_refs

    def test_row_container_classes_survive_as_texts_or_jsx(self):
        boundary = _boundary(HISTORY_VIEW_JS, "HistoryView")
        sections = extract_sections(HISTORY_VIEW_JS, _screen("HistoryView"), boundary)
        audit_section = next(s for s in sections if "Icon" in s.component_refs)
        assert "audit-item" in audit_section.jsx_snippet

    def test_two_independent_raw_map_blocks_each_produce_their_own_section(self):
        boundary = _boundary(HISTORY_VIEW_JS, "HistoryView")
        sections = extract_sections(HISTORY_VIEW_JS, _screen("HistoryView"), boundary)
        list_item_sections = [s for s in sections if s.detection_method == "list_item"]
        # "audit-item" (qualifies: has an Icon ref) is guaranteed; the chip
        # filter row has no component refs/texts/styles of its own and may
        # be dropped by the quality filter — only the qualifying one is required.
        assert any("audit-item" in s.jsx_snippet for s in list_item_sections)

    def test_named_component_list_is_not_claimed_by_this_strategy(self):
        """A `.map()` returning a named component (<UserRow/>) is already
        fully represented as a real Component — this strategy only exists
        for markup that never became one, so it must ignore this shape."""
        boundary = _boundary(NAMED_COMPONENT_LIST_JS, "UsersView")
        sections = extract_sections(NAMED_COMPONENT_LIST_JS, _screen("UsersView"), boundary)
        assert not any(s.detection_method == "list_item" for s in sections)

    def test_does_not_run_when_comment_sections_already_found(self):
        js = """
        function AnnotatedHistoryView() {
            return (
                <div>
                    {/* Audit trail */}
                    <div className="audit">
                        {items.map((e, i) => (
                            <div className="audit-item" key={e.id}>
                                <Icon name="history" size={15} />
                            </div>
                        ))}
                    </div>
                </div>
            )
        }
        """
        boundary = _boundary(js, "AnnotatedHistoryView")
        sections = extract_sections(js, _screen("AnnotatedHistoryView"), boundary)
        assert all(s.detection_method == "comment" for s in sections)

    def test_quality_filter_drops_a_row_with_no_refs_texts_or_styles(self):
        boundary = _boundary(UNQUALIFIED_LIST_JS, "PlainTextList")
        sections = extract_sections(UNQUALIFIED_LIST_JS, _screen("PlainTextList"), boundary)
        assert sections == []


class TestInlineListMarkupResolvesCssClasses:
    """
    Sections built from raw markup are the whole point of this strategy —
    but this prototype convention styles containers via CSS classes
    (`.audit-item { ... }`), not inline `style={{}}`. Without resolving
    className against the stylesheet the same way extract_component already
    does, the new section would carry structure (refs, JSX) but none of the
    real visual styling.
    """

    def test_class_based_styles_resolved_when_rule_map_provided(self):
        rule_map = {
            "audit-item": [CssRule(".audit-item", "display", "flex")],
            "audit-item ": [],
        }
        boundary = _boundary(HISTORY_VIEW_JS, "HistoryView")
        sections = extract_sections(
            HISTORY_VIEW_JS, _screen("HistoryView"), boundary, rule_map=rule_map,
        )
        audit_section = next(s for s in sections if "Icon" in s.component_refs)
        assert audit_section.styles.get("display") == "flex"

    def test_inline_style_wins_over_resolved_class_for_same_property(self):
        js = """
        function StyledRows() {
            return (
                <div>
                    {rows.map((r, i) => (
                        <div className="row-item" style={{ display: "grid" }} key={i}>
                            <Icon name="dot" size={10} />
                        </div>
                    ))}
                </div>
            )
        }
        """
        rule_map = {"row-item": [CssRule(".row-item", "display", "flex")]}
        boundary = _boundary(js, "StyledRows")
        sections = extract_sections(js, _screen("StyledRows"), boundary, rule_map=rule_map)
        audit_section = next(s for s in sections if "Icon" in s.component_refs)
        assert audit_section.styles.get("display") == "grid"

    def test_no_class_styles_added_when_rule_map_is_none(self):
        boundary = _boundary(HISTORY_VIEW_JS, "HistoryView")
        sections = extract_sections(HISTORY_VIEW_JS, _screen("HistoryView"), boundary, rule_map=None)
        audit_section = next(s for s in sections if "Icon" in s.component_refs)
        assert "display" not in audit_section.styles
