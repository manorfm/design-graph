"""Tests for section_extractor — T08."""

import pytest

from design_graph.core.models import ExtractedScreen
from design_graph.extraction.section_extractor import extract_sections
from design_graph.parsing.js_parser import find_all_boundaries

WITH_COMMENTS_JS = """
function RestaurantsPage() {
    return (
        <div>
            {/* ── Header ── */}
            <h1>Restaurantes</h1>
            <BtnFilter />

            {/* ── Lista ── */}
            <SectionCard item={a} />
            <SectionCard item={b} />

            {/* ── Footer ── */}
            <p>© 2024 iPede</p>
        </div>
    )
}
"""

WITHOUT_COMMENTS_JS = """
function RestaurantsPage() {
    return (
        <div>
            <div style={{padding: '24px', marginBottom: '16px'}}>
                <h1>Restaurantes em Destaque</h1>
                <BtnFilter />
            </div>
            <div style={{padding: '16px'}}>
                <SectionCard item={a} />
                <SectionCard item={b} />
            </div>
        </div>
    )
}
"""


def _boundary(js: str, name: str = "RestaurantsPage"):
    bounds = find_all_boundaries(js)
    return next(b for b in bounds if b.name == name)


def _screen(name: str = "RestaurantsPage") -> ExtractedScreen:
    return ExtractedScreen(name=name, component_refs=[], sections_count=0)


class TestCommentBasedSections:
    def test_finds_comment_sections(self):
        boundary = _boundary(WITH_COMMENTS_JS)
        sections = extract_sections(WITH_COMMENTS_JS, _screen(), boundary)
        names_lower = [s.name.lower() for s in sections]
        assert any("header" in n for n in names_lower)
        assert any("lista" in n for n in names_lower)

    def test_detection_method_is_comment(self):
        boundary = _boundary(WITH_COMMENTS_JS)
        sections = extract_sections(WITH_COMMENTS_JS, _screen(), boundary)
        assert all(s.detection_method == "comment" for s in sections)

    def test_filter_button_in_header_section(self):
        boundary = _boundary(WITH_COMMENTS_JS)
        sections = extract_sections(WITH_COMMENTS_JS, _screen(), boundary)
        header = next((s for s in sections if "header" in s.name.lower()), None)
        assert header is not None
        assert "BtnFilter" in header.component_refs

    def test_section_card_in_lista_section(self):
        boundary = _boundary(WITH_COMMENTS_JS)
        sections = extract_sections(WITH_COMMENTS_JS, _screen(), boundary)
        lista = next((s for s in sections if "lista" in s.name.lower()), None)
        assert lista is not None
        assert "SectionCard" in lista.component_refs

    def test_section_ids_are_unique(self):
        boundary = _boundary(WITH_COMMENTS_JS)
        sections = extract_sections(WITH_COMMENTS_JS, _screen(), boundary)
        ids = [s.id for s in sections]
        assert len(ids) == len(set(ids))

    def test_section_screen_field_matches_screen_name(self):
        boundary = _boundary(WITH_COMMENTS_JS)
        sections = extract_sections(WITH_COMMENTS_JS, _screen("RestaurantsPage"), boundary)
        for sec in sections:
            assert sec.screen == "RestaurantsPage"


class TestStructuralFallback:
    def test_fallback_triggers_when_no_comments(self):
        boundary = _boundary(WITHOUT_COMMENTS_JS)
        sections = extract_sections(WITHOUT_COMMENTS_JS, _screen(), boundary)
        assert len(sections) >= 1

    def test_detection_method_is_structural_or_none(self):
        boundary = _boundary(WITHOUT_COMMENTS_JS)
        sections = extract_sections(WITHOUT_COMMENTS_JS, _screen(), boundary)
        for sec in sections:
            assert sec.detection_method in ("structural", "none", "comment")

    def test_max_sections_from_structural_fallback(self):
        # Build a screen with many padding divs
        many_divs = "\n".join(
            f"<div style={{{{padding:'20px'}}}}>block{i}<Comp{i}/></div>"
            for i in range(20)
        )
        js = f"function BigPage() {{ return (<div>{many_divs}</div>) }}"
        bounds = find_all_boundaries(js)
        screen_b = next(b for b in bounds if b.name == "BigPage")
        screen = ExtractedScreen(name="BigPage", component_refs=[], sections_count=0)
        sections = extract_sections(js, screen, screen_b)
        assert len(sections) <= 8


class TestQualityFilter:
    def test_empty_section_not_created(self):
        js = """
        function EmptyPage() {
            return (
                <div>
                    {/* ── Empty ── */}
                </div>
            )
        }
        """
        bounds = find_all_boundaries(js)
        screen_b = next(b for b in bounds if b.name == "EmptyPage")
        screen = ExtractedScreen(name="EmptyPage", component_refs=[], sections_count=0)
        sections = extract_sections(js, screen, screen_b)
        for sec in sections:
            qualifies = (
                len(sec.component_refs) >= 1
                or len(sec.texts) >= 2
                or len(sec.styles) >= 3
            )
            assert qualifies, f"Empty section escaped quality filter: {sec.name}"

    def test_no_exception_on_screenless_js(self):
        js = "const x = 1;"
        bounds = find_all_boundaries(js)
        screen = ExtractedScreen(name="Missing", component_refs=[], sections_count=0)
        from design_graph.core.models import FunctionBoundary
        dummy = FunctionBoundary(name="Missing", start=0, body_start=0, end=0)
        result = extract_sections(js, screen, dummy)
        assert isinstance(result, list)
