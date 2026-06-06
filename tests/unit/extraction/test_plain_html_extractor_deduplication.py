"""
Tests for plain_html_component_extractor.py deduplication and style extraction.

Targets:
  - dom_patterns_to_extracted_components: keep higher-count when name collision (155, 157-159)
  - dom_patterns_to_extracted_components: skip lower-count duplicate (line 144 continue)
  - _extract_inline_styles: styles capped at 20 (line 102)
"""

from __future__ import annotations

import pytest

from design_graph.core.models import DOMPattern
from design_graph.extraction.plain_html_component_extractor import (
    _extract_inline_styles,
    dom_patterns_to_extracted_components,
)


def _pattern(name: str, count: int, sig: str = "div>img,h3,p") -> DOMPattern:
    return DOMPattern(
        signature=sig,
        count=count,
        first_example=f'<div class="card"><h3>{name}</h3></div>',
        inferred_name=name,
        semantic_type="card",
    )


# ── Deduplication: keep higher count ─────────────────────────────────────────

class TestDomPatternDeduplication:
    def test_keeps_higher_count_when_name_collides(self):
        patterns = [
            _pattern("Card", count=3, sig="div.card-v1>img,h3"),
            _pattern("Card", count=7, sig="div.card-v2>img,h3,p"),  # higher count
        ]
        result = dom_patterns_to_extracted_components(patterns)
        assert len(result) == 1
        assert result[0].occurrence == 7

    def test_keeps_first_when_second_has_lower_count(self):
        patterns = [
            _pattern("Widget", count=8),
            _pattern("Widget", count=2),  # lower — keep first
        ]
        result = dom_patterns_to_extracted_components(patterns)
        assert len(result) == 1
        assert result[0].occurrence == 8

    def test_three_collisions_keeps_highest_count(self):
        patterns = [
            _pattern("Tile", count=3),
            _pattern("Tile", count=9),  # highest
            _pattern("Tile", count=5),
        ]
        result = dom_patterns_to_extracted_components(patterns)
        assert len(result) == 1
        assert result[0].occurrence == 9

    def test_different_names_not_deduplicated(self):
        patterns = [
            _pattern("Card",   count=4),
            _pattern("NavBar", count=1, sig="nav>a,a,a"),
        ]
        result = dom_patterns_to_extracted_components(patterns)
        assert len(result) == 2

    def test_single_pattern_not_affected_by_dedup(self):
        patterns = [_pattern("Solo", count=5)]
        result = dom_patterns_to_extracted_components(patterns)
        assert len(result) == 1
        assert result[0].occurrence == 5


# ── _extract_inline_styles: styles capped at 20 ──────────────────────────────

class TestExtractInlineStylesCap:
    def test_styles_capped_at_20_per_component(self):
        # Build HTML with 25+ inline style properties
        props = "; ".join(f"prop-{i}: {i}px" for i in range(25))
        html = f'<div style="{props}"><span>content</span></div>'
        styles = _extract_inline_styles(html, "TestComp")
        assert len(styles) <= 20

    def test_style_ids_are_unique(self):
        props = "; ".join(f"background-color-{i}: #abc{i:03d}" for i in range(15))
        html = f'<div style="{props}"><p>text</p></div>'
        styles = _extract_inline_styles(html, "UniqueComp")
        ids = [s.id for s in styles]
        assert len(ids) == len(set(ids))

    def test_empty_html_returns_empty_styles(self):
        styles = _extract_inline_styles("", "EmptyComp")
        assert styles == []

    def test_html_without_style_attr_returns_empty(self):
        html = '<div class="card"><h3>Name</h3></div>'
        styles = _extract_inline_styles(html, "NoStyle")
        assert styles == []

    def test_element_field_matches_comp_name(self):
        html = '<div style="color: red; font-size: 14px"><p>x</p></div>'
        styles = _extract_inline_styles(html, "MyComponent")
        for s in styles:
            assert s.element == "MyComponent"

    def test_state_is_always_default(self):
        html = '<div style="color: blue"><p>x</p></div>'
        styles = _extract_inline_styles(html, "Comp")
        for s in styles:
            assert s.state == "default"
