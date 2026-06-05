"""Tests for html_parser — T05."""

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from design_graph.core.models import DOMPattern
from design_graph.parsing.html_parser import extract_dom_patterns, extract_semantic_sections

FIXTURE_DIR = Path(__file__).parent.parent.parent / "fixtures"

PLAIN_HTML = (FIXTURE_DIR / "plain.html").read_text()
PLAIN_SOUP = BeautifulSoup(PLAIN_HTML, "html.parser")

CARD_HTML = """
<html><body>
  <nav class="navbar"><a href="/">Home</a></nav>
  <main>
    <div class="card"><img src="a.jpg"><h3>A</h3><p>Desc A</p><button>Ver</button></div>
    <div class="card"><img src="b.jpg"><h3>B</h3><p>Desc B</p><button>Ver</button></div>
    <div class="card"><img src="c.jpg"><h3>C</h3><p>Desc C</p><button>Ver</button></div>
    <div class="card"><img src="d.jpg"><h3>D</h3><p>Desc D</p><button>Ver</button></div>
  </main>
  <footer><p>Footer</p></footer>
</body></html>
"""
CARD_SOUP = BeautifulSoup(CARD_HTML, "html.parser")


class TestExtractDOMPatterns:
    def test_detects_repeated_card_pattern(self):
        patterns = extract_dom_patterns(CARD_SOUP, min_count=3)
        assert len(patterns) >= 1

    def test_count_reflects_actual_repetitions(self):
        patterns = extract_dom_patterns(CARD_SOUP, min_count=3)
        card = next((p for p in patterns if "card" in p.signature.lower()), None)
        assert card is not None
        assert card.count >= 4

    def test_min_count_filter_respected(self):
        high = extract_dom_patterns(CARD_SOUP, min_count=5)
        low  = extract_dom_patterns(CARD_SOUP, min_count=1)
        assert len(low) >= len(high)

    def test_returns_dom_pattern_instances(self):
        patterns = extract_dom_patterns(CARD_SOUP, min_count=3)
        for p in patterns:
            assert isinstance(p, DOMPattern)

    def test_first_example_is_non_empty_html(self):
        patterns = extract_dom_patterns(CARD_SOUP, min_count=3)
        for p in patterns:
            assert len(p.first_example) > 0

    def test_first_example_truncated_to_600_chars(self):
        patterns = extract_dom_patterns(CARD_SOUP, min_count=3)
        for p in patterns:
            assert len(p.first_example) <= 600

    def test_inferred_name_starts_with_uppercase(self):
        patterns = extract_dom_patterns(CARD_SOUP, min_count=3)
        for p in patterns:
            assert p.inferred_name[0].isupper(), f"Bad name: {p.inferred_name!r}"

    def test_signature_contains_no_spaces(self):
        patterns = extract_dom_patterns(CARD_SOUP, min_count=3)
        for p in patterns:
            assert " " not in p.signature

    def test_simple_standalone_spans_excluded(self):
        # <span> alone repeated many times should not qualify (signature too short)
        html = "<span>A</span>" * 10
        soup = BeautifulSoup(html, "html.parser")
        patterns = extract_dom_patterns(soup, min_count=3)
        assert all(len(p.signature) >= 10 for p in patterns)

    def test_plain_html_fixture_has_card_pattern(self):
        patterns = extract_dom_patterns(PLAIN_SOUP, min_count=3)
        assert len(patterns) >= 1

    def test_empty_soup_returns_empty_list(self):
        patterns = extract_dom_patterns(BeautifulSoup("", "html.parser"), min_count=3)
        assert patterns == []


class TestExtractSemanticSections:
    def test_finds_nav_element(self):
        sections = extract_semantic_sections(CARD_SOUP)
        tags = [s["tag"] for s in sections]
        assert "nav" in tags

    def test_finds_main_or_section(self):
        sections = extract_semantic_sections(CARD_SOUP)
        tags = [s["tag"] for s in sections]
        assert "main" in tags or "section" in tags

    def test_finds_footer_element(self):
        sections = extract_semantic_sections(CARD_SOUP)
        tags = [s["tag"] for s in sections]
        assert "footer" in tags

    def test_plain_html_fixture_has_sections(self):
        sections = extract_semantic_sections(PLAIN_SOUP)
        assert len(sections) >= 3

    def test_each_section_has_html_field(self):
        sections = extract_semantic_sections(CARD_SOUP)
        for s in sections:
            assert "html" in s
            assert len(s["html"]) > 0

    def test_each_section_has_name_field(self):
        sections = extract_semantic_sections(CARD_SOUP)
        for s in sections:
            assert "name" in s
            assert s["name"]

    def test_each_section_has_tag_field(self):
        sections = extract_semantic_sections(CARD_SOUP)
        for s in sections:
            assert "tag" in s

    def test_heading_used_as_section_name(self):
        html = "<main><h2>Cardápio</h2><p>items here</p></main>"
        soup = BeautifulSoup(html, "html.parser")
        sections = extract_semantic_sections(soup)
        assert any("Cardápio" in s.get("name", "") for s in sections)

    def test_empty_soup_returns_empty_list(self):
        assert extract_semantic_sections(BeautifulSoup("", "html.parser")) == []

    def test_no_exception_on_malformed_html(self):
        broken = BeautifulSoup("<<<nav broken>>>", "html.parser")
        result = extract_semantic_sections(broken)
        assert isinstance(result, list)
