"""
Tests for parsing layer edge cases not covered by existing tests.

Targets:
  - format_detector.py: Tailwind detection (lines 59-60)
  - js_parser.py: function without opening brace → fallback (line 89),
    boundary clipping when overlap detected (lines 128, 142-147)
  - token_extractor.py: colors with < 2 occurrences filtered (line 101),
    spacing with < 2 occurrences filtered (lines 134-135)
"""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from design_graph.parsing.format_detector import TAILWIND, detect
from design_graph.parsing.js_parser import (
    find_function_boundaries,
    find_function_end,
)
from design_graph.parsing.token_extractor import extract_tokens
from design_graph.core.models import RawSources
from design_graph.core.patterns import RE_COMP_FN


# ── format_detector: Tailwind detection ──────────────────────────────────────

class TestTailwindDetection:
    def _detect(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        return detect(html, soup)

    def test_tailwind_detected_by_utility_class_patterns(self):
        html = """<html><head><style>
            .flex{display:flex}
            .p-4{padding:1rem}
            .text-sm{font-size:0.875rem}
        </style></head><body></body></html>"""
        fmt = self._detect(html)
        assert fmt == TAILWIND

    def test_tailwind_detected_by_grid_pattern(self):
        html = """<html><head><style>
            .grid{display:grid}
            .gap-4{gap:1rem}
        </style></head></html>"""
        fmt = self._detect(html)
        assert fmt == TAILWIND

    def test_no_tailwind_returns_plain_html(self):
        html = "<html><body><p>Hello</p></body></html>"
        fmt = self._detect(html)
        assert fmt != TAILWIND


# ── js_parser: function without body brace ────────────────────────────────────

class TestFunctionEndFallback:
    def test_no_brace_within_500_chars_uses_fallback(self):
        # A "function declaration" with no opening brace nearby
        js = "function MyComp() " + " " * 600 + "{ return <div/>; }"
        end = find_function_end(js, 0)
        # Should return fallback (fn_start + JS_FUNCTION_FALLBACK_WINDOW)
        from design_graph.core.constants import JS_FUNCTION_FALLBACK_WINDOW
        assert end == min(JS_FUNCTION_FALLBACK_WINDOW, len(js))


# ── js_parser: boundary clipping ─────────────────────────────────────────────

class TestBoundaryClipping:
    def test_clipped_boundaries_do_not_overlap(self):
        """Functions whose raw ends overlap should be clipped to non-overlap."""
        js = """
        function CompA() {
          return <div><CompB /></div>;
        }
        function CompB() {
          return <span>B</span>;
        }
        """
        bounds = find_function_boundaries(js, RE_COMP_FN)
        # Verify non-overlap invariant
        for i in range(len(bounds) - 1):
            assert bounds[i].end <= bounds[i + 1].start, (
                f"{bounds[i].name}.end ({bounds[i].end}) > "
                f"{bounds[i + 1].name}.start ({bounds[i + 1].start})"
            )

    def test_clipped_boundary_logged_name_preserved(self):
        """After clipping, the boundary name must stay correct."""
        js = """
        function Alpha() { return <div><Beta /></div>; }
        function Beta()  { return <span>B</span>; }
        """
        bounds = find_function_boundaries(js, RE_COMP_FN)
        names = [b.name for b in bounds]
        assert "Alpha" in names
        assert "Beta" in names


# ── token_extractor: single-occurrence filter ────────────────────────────────

class TestTokenOccurrenceFilter:
    def _sources(self, js: str) -> RawSources:
        return RawSources(js=js, css="", inner_html="", html_hash="x", format="plain_html")

    def test_color_with_one_occurrence_filtered_out(self):
        js = "style={{color:'#unique1a2b3c'}}"  # appears only once
        tokens = extract_tokens(self._sources(js))
        values = {t.value for t in tokens}
        assert "#unique1a2b3c" not in values

    def test_color_with_two_occurrences_included(self):
        # Repeat twice — should be included
        js = "style={{color:'#aabbcc'}} " * 2
        tokens = extract_tokens(self._sources(js))
        values = {t.value for t in tokens}
        assert "#aabbcc" in values

    def test_spacing_with_one_occurrence_filtered(self):
        js = "style={{padding:'99px'}}"  # only once
        tokens = extract_tokens(self._sources(js))
        values = {t.value for t in tokens if t.category == "spacing"}
        assert "99px" not in values

    def test_spacing_with_two_occurrences_included(self):
        js = "style={{padding:'88px'}} " * 2
        tokens = extract_tokens(self._sources(js))
        values = {t.value for t in tokens if t.category == "spacing"}
        assert "88px" in values
