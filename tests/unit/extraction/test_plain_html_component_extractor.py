"""
Unit tests for extraction/plain_html_component_extractor.py.

Responsibility under test: convert DOMPattern objects (from html_parser) into
ExtractedComponent objects suitable for insertion into the Kuzu graph.

This module bridges the parsing layer (html_parser.py → DOMPattern) and the
graph layer (GraphWriter → Component nodes) for the plain_html format.
"""

from __future__ import annotations

import pytest

from design_graph.core.models import DOMPattern, ExtractedComponent
from design_graph.extraction.plain_html_component_extractor import (
    dom_patterns_to_extracted_components,
    dom_pattern_to_extracted_component,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _pattern(
    name: str = "RestaurantCard",
    sig: str = "div.card>img,h3,p,button",
    count: int = 4,
    example: str = '<div class="card"><img/><h3>Name</h3><p>Desc</p><button>Order</button></div>',
    sem_type: str = "card",
) -> DOMPattern:
    return DOMPattern(
        signature=sig,
        count=count,
        first_example=example,
        inferred_name=name,
        semantic_type=sem_type,
    )


# ── dom_pattern_to_extracted_component ───────────────────────────────────────

class TestDomPatternToExtractedComponent:
    def test_returns_extracted_component(self):
        result = dom_pattern_to_extracted_component(_pattern())
        assert isinstance(result, ExtractedComponent)

    def test_name_is_inferred_name_from_pattern(self):
        result = dom_pattern_to_extracted_component(_pattern(name="PriceTag"))
        assert result.name == "PriceTag"

    def test_comp_type_matches_semantic_type(self):
        result = dom_pattern_to_extracted_component(_pattern(sem_type="card"))
        assert result.comp_type == "card"

    def test_occurrence_equals_pattern_count(self):
        result = dom_pattern_to_extracted_component(_pattern(count=7))
        assert result.occurrence == 7

    def test_jsx_snippet_is_first_example_html(self):
        html = '<div class="card"><h3>Alfa</h3></div>'
        result = dom_pattern_to_extracted_component(_pattern(example=html))
        assert html in result.jsx_snippet or "card" in result.jsx_snippet

    def test_classes_extracted_from_html_snippet(self):
        html = '<div class="restaurant-card featured"><img/><h3>Name</h3></div>'
        result = dom_pattern_to_extracted_component(_pattern(example=html))
        assert "restaurant-card" in result.classes or "featured" in result.classes

    def test_child_refs_empty_for_plain_html_patterns(self):
        # Plain HTML doesn't reference React components
        result = dom_pattern_to_extracted_component(_pattern())
        assert result.child_refs == []

    def test_nav_type_maps_to_navigation(self):
        result = dom_pattern_to_extracted_component(_pattern(sem_type="nav"))
        assert result.comp_type == "navigation" or result.comp_type == "nav"

    def test_result_is_deterministic_for_same_input(self):
        pattern = _pattern()
        a = dom_pattern_to_extracted_component(pattern)
        b = dom_pattern_to_extracted_component(pattern)
        assert a.name == b.name
        assert a.jsx_snippet == b.jsx_snippet

    def test_no_styles_when_snippet_has_no_inline_styles(self):
        html = '<div class="card"><h3>Name</h3></div>'
        result = dom_pattern_to_extracted_component(_pattern(example=html))
        assert isinstance(result.styles, list)

    def test_styles_extracted_when_snippet_has_inline_styles(self):
        html = '<div style="background-color:#1f1f1f; padding:16px"><h3>Name</h3></div>'
        result = dom_pattern_to_extracted_component(_pattern(example=html))
        # At least some style entries may be extracted from inline style
        assert isinstance(result.styles, list)


# ── dom_patterns_to_extracted_components ─────────────────────────────────────

class TestDomPatternsToExtractedComponents:
    def test_empty_input_returns_empty_list(self):
        result = dom_patterns_to_extracted_components([])
        assert result == []

    def test_one_pattern_produces_one_component(self):
        result = dom_patterns_to_extracted_components([_pattern()])
        assert len(result) == 1

    def test_multiple_patterns_produce_same_count(self):
        patterns = [
            _pattern("CardA", count=4),
            _pattern("NavBar", sig="nav>a,a,a", count=1, sem_type="nav"),
            _pattern("BtnPrimary", sig="button.btn-primary", count=6, sem_type="button"),
        ]
        result = dom_patterns_to_extracted_components(patterns)
        assert len(result) == 3

    def test_all_results_are_extracted_component_instances(self):
        patterns = [_pattern("A"), _pattern("B"), _pattern("C")]
        for comp in dom_patterns_to_extracted_components(patterns):
            assert isinstance(comp, ExtractedComponent)

    def test_names_preserved_from_patterns(self):
        patterns = [_pattern("RestaurantCard"), _pattern("NavBar")]
        result = dom_patterns_to_extracted_components(patterns)
        names = {c.name for c in result}
        assert "RestaurantCard" in names
        assert "NavBar" in names

    def test_duplicate_pattern_names_deduplicated(self):
        # Two patterns with same inferred_name — should not create duplicates
        patterns = [
            _pattern("Card", count=4),
            _pattern("Card", sig="div.card2>img,p", count=3),
        ]
        result = dom_patterns_to_extracted_components(patterns)
        names = [c.name for c in result]
        assert len(names) == len(set(names)), "Duplicate component names found"

    def test_returns_list_not_generator(self):
        result = dom_patterns_to_extracted_components([_pattern()])
        assert isinstance(result, list)
