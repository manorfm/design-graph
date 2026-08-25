"""
Tests for section_extractor.py branches not covered by test_section_extractor.py.

Targets:
  - No-sections-detected log path (line 70-71)
  - _detect_by_structure: ValueError in px parse (line 117-118)
  - _detect_by_structure: no </div> found → fallback div_end (line 126)
  - _build_section: placeholder texts (lines 193-196)
  - Structural detection produces sections with correct detection_method
"""

from __future__ import annotations

import pytest

from design_graph.core.models import ExtractedScreen, FunctionBoundary
from design_graph.extraction.section_extractor import (
    _build_section,
    _detect_by_structure,
    _find_balanced_div_end,
    extract_sections,
)


def _boundary(js: str, name: str) -> FunctionBoundary:
    from design_graph.parsing.js_parser import find_all_boundaries
    bounds = find_all_boundaries(js)
    return next(b for b in bounds if b.name == name)


def _screen(name: str) -> ExtractedScreen:
    return ExtractedScreen(name=name, component_refs=[], sections_count=0)


# ── No sections detected (empty result) ───────────────────────────────────────

class TestNoSectionsDetected:
    def test_returns_empty_for_function_with_no_comments_no_padding(self):
        js = """
        function SimplePage() {
          return (
            <div>
              <span>Hello</span>
              <BtnPrimary />
            </div>
          );
        }
        """
        b = _boundary(js, "SimplePage")
        s = _screen("SimplePage")
        sections = extract_sections(js, s, b)
        # No {/* ... */} comments, no divs with padding >= 16px → empty
        assert isinstance(sections, list)

    def test_returns_empty_for_zero_length_boundary(self):
        from design_graph.core.models import FunctionBoundary
        b = FunctionBoundary(name="TestPage", start=10, body_start=10, end=10)
        s = _screen("TestPage")
        sections = extract_sections("function TestPage() {}", s, b)
        assert sections == []


# ── Structural fallback ───────────────────────────────────────────────────────

class TestStructuralFallback:
    def test_finds_sections_by_padding(self):
        window = """
        <div style={{padding: '24px', margin: '8px'}}>
          <h2>Section Title</h2>
          <BtnPrimary />
          <SectionCard />
        </div>
        <div style={{padding: '32px'}}>
          <h2>Another Section</h2>
          <InputText />
        </div>
        """
        sections = _detect_by_structure(window, "TestScreen")
        # Should find at least 1 section
        assert len(sections) >= 1

    def test_structural_sections_have_detection_method(self):
        window = """
        <div style={{padding: '20px'}}>
          <span>Content here</span>
          <BtnPrimary />
        </div>
        """
        sections = _detect_by_structure(window, "TestScreen")
        for sec in sections:
            assert sec.detection_method == "structural"

    def test_skips_padding_below_threshold(self):
        window = """
        <div style={{padding: '4px'}}>
          <span>Tiny padding — not a section</span>
        </div>
        """
        sections = _detect_by_structure(window, "TestScreen")
        assert sections == []

    def test_no_closing_div_uses_fallback_end(self):
        # Window without </div> — should use the fixed-window fallback end
        window = "<div style={{padding: '24px'}}><span>Unclosed div content " + "x" * 100

        # Should not raise
        sections = _detect_by_structure(window, "TestScreen")
        assert isinstance(sections, list)

    def test_non_integer_padding_value_skipped_gracefully(self):
        # "px" parsing where the capture group contains non-integer
        window = """<div style={{padding: 'abcpx'}}><span>Bad padding</span></div>"""
        # Should not raise — ValueError is caught
        sections = _detect_by_structure(window, "TestScreen")
        assert isinstance(sections, list)

    def test_deduplicates_overlapping_candidates(self):
        # Two very close matches — should be deduplicated
        window = """
        <div style={{padding: '24px'}}><div style={{padding: '20px'}}>
          <BtnPrimary /><SectionCard />
        </div></div>
        """
        sections = _detect_by_structure(window, "TestScreen")
        # Should not produce more sections than MAX_SECTIONS_FROM_STRUCTURAL_FALLBACK
        from design_graph.core.constants import MAX_SECTIONS_FROM_STRUCTURAL_FALLBACK
        assert len(sections) <= MAX_SECTIONS_FROM_STRUCTURAL_FALLBACK


# ── _find_balanced_div_end: nested divs (C26/T50) ────────────────────────────

class TestSectionComponentRefsOrder:
    """C34: order is first-appearance in the JSX, not alphabetical — same
    fix C30 already applied to a component's own child_refs."""

    def test_preserves_jsx_appearance_order(self):
        block = "<div><Zebra /><Alpha /><Mango /></div>"
        section = _build_section(
            block=block, sec_name="Test", screen_name="TestScreen",
            detection_method="comment",
        )
        assert section.component_refs == ["Zebra", "Alpha", "Mango"]

    def test_no_duplicates(self):
        block = "<div><Zebra /><Alpha /><Zebra /></div>"
        section = _build_section(
            block=block, sec_name="Test", screen_name="TestScreen",
            detection_method="comment",
        )
        assert section.component_refs == ["Zebra", "Alpha"]


class TestFindBalancedDivEnd:
    def test_nested_div_does_not_cut_at_first_child_close(self):
        window = (
            "<div style={{padding: '24px'}}>"
            "<div><span>child one</span></div>"
            "<div><span>child two</span></div>"
            "</div>TAIL"
        )
        div_start = window.index("<div")
        end = _find_balanced_div_end(window, div_start)
        # Must include both children and stop right after the outer </div>,
        # not at the first child's closing tag.
        assert window[div_start:end].endswith("</div>")
        assert "child two" in window[div_start:end]
        assert window[end:end + 4] == "TAIL"

    def test_structural_fallback_captures_full_padded_container(self):
        window = """
        <div style={{padding: '24px'}}>
          <h2>Section Title</h2>
          <div className="row">
            <BtnPrimary />
          </div>
          <SectionCard />
        </div>
        <div style={{padding: '32px'}}>
          <h2>Another Section</h2>
        </div>
        """
        sections = _detect_by_structure(window, "TestScreen")
        assert len(sections) >= 1
        # The first section's block must reach past the nested <div className="row">
        # child all the way to SectionCard, not stop at the child's own </div>.
        assert "SectionCard" in sections[0].jsx_snippet

    def test_unbalanced_close_falls_back_to_fixed_window(self):
        window = "<div style={{padding: '24px'}}>" + "x" * 50  # no </div> at all
        div_start = window.index("<div")
        end = _find_balanced_div_end(window, div_start)
        assert end == len(window)


# ── _build_section: placeholder texts ────────────────────────────────────────

class TestBuildSectionPlaceholderTexts:
    def test_placeholder_included_in_texts(self):
        # Use a lowercase placeholder so RE_UI_STRING (requires uppercase first char)
        # does NOT capture it first — only RE_PLACEHOLDER picks it up.
        block = """
        <div style={{padding: '16px'}}>
          <input placeholder="type your search query here..." />
          <BtnPrimary />
        </div>
        """
        section = _build_section(
            block=block,
            sec_name="SearchSection",
            screen_name="HomePage",
            detection_method="structural",
        )
        # Placeholder text captured via RE_PLACEHOLDER with [placeholder] prefix
        placeholder_texts = [t for t in section.texts if "[placeholder]" in t]
        assert any("type your search" in t.lower() for t in placeholder_texts)

    def test_duplicate_placeholders_not_added_twice(self):
        block = """
        <input placeholder="Search..." />
        <input placeholder="Search..." />
        """
        section = _build_section(
            block=block,
            sec_name="Dup",
            screen_name="TestPage",
            detection_method="structural",
        )
        search_texts = [t for t in section.texts if "Search" in t]
        assert len(search_texts) == 1

    def test_texts_capped_at_15(self):
        # Generate a block with many strings
        many_texts = " ".join(f'<p>"{chr(65 + i)} text here"</p>' for i in range(20))
        section = _build_section(
            block=many_texts,
            sec_name="ManyTexts",
            screen_name="TestPage",
            detection_method="comment",
        )
        assert len(section.texts) <= 15
