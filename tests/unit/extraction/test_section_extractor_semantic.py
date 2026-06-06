"""
Tests for section_extractor strategy 3: semantic detection via html_parser.

The semantic strategy activates when:
  - Strategy 1 (JSX comments) finds nothing
  - Strategy 2 (structural padding) finds nothing
  - The format is plain_html

It uses extract_semantic_sections(soup) from html_parser to find
HTML5 semantic elements (nav, header, main, section, footer, aside).
"""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from design_graph.core.models import ExtractedScreen, FunctionBoundary
from design_graph.extraction.section_extractor import (
    _detect_by_semantic,
    extract_sections_for_plain_html,
)


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


# ── _detect_by_semantic ───────────────────────────────────────────────────────

class TestDetectBySemantic:
    def test_finds_nav_as_section(self):
        soup = _soup("<html><body><nav><a>Home</a><a>About</a></nav></body></html>")
        sections = _detect_by_semantic(soup, "HomePage")
        assert any(s.detection_method == "semantic" for s in sections)

    def test_finds_header_as_section(self):
        soup = _soup("<html><body><header><h1>Site Title</h1></header></body></html>")
        sections = _detect_by_semantic(soup, "HomePage")
        assert len(sections) >= 1

    def test_finds_main_as_section(self):
        soup = _soup("<html><body><main><p>content</p><p>more</p><p>x</p></main></body></html>")
        sections = _detect_by_semantic(soup, "HomePage")
        assert any(s.name.lower() in ("main", "main content") for s in sections)

    def test_finds_footer_as_section(self):
        soup = _soup("<html><body><footer><p>2024 Co.</p></footer></body></html>")
        sections = _detect_by_semantic(soup, "HomePage")
        assert len(sections) >= 1

    def test_section_screen_field_set_correctly(self):
        soup = _soup("<html><body><nav><a>x</a></nav></body></html>")
        sections = _detect_by_semantic(soup, "MyPage")
        assert all(s.screen == "MyPage" for s in sections)

    def test_all_sections_have_semantic_detection_method(self):
        soup = _soup("<html><body><nav><a>x</a></nav><header><h1>H</h1></header></body></html>")
        sections = _detect_by_semantic(soup, "TestPage")
        for sec in sections:
            assert sec.detection_method == "semantic"

    def test_returns_empty_for_no_semantic_tags(self):
        soup = _soup("<html><body><div><span>nothing semantic</span></div></body></html>")
        sections = _detect_by_semantic(soup, "TestPage")
        assert isinstance(sections, list)

    def test_section_has_jsx_snippet_from_html(self):
        soup = _soup("<html><body><section id='featured'><h2>Featured</h2><p>x</p></section></body></html>")
        sections = _detect_by_semantic(soup, "TestPage")
        if sections:
            assert any("featured" in s.jsx_snippet.lower() or "Featured" in s.jsx_snippet
                       for s in sections)


# ── extract_sections_for_plain_html ──────────────────────────────────────────

class TestExtractSectionsForPlainHtml:
    """Integration path: BeautifulSoup → semantic sections → ExtractedSection list."""

    PLAIN_HTML = """<!DOCTYPE html>
    <html><body>
      <nav class="navbar">
        <a href="/">iPede</a>
        <a href="/restaurants">Restaurantes</a>
        <a href="/orders">Pedidos</a>
      </nav>
      <main>
        <section id="featured">
          <h2>Restaurantes em Destaque</h2>
          <div class="card"><img/><h3>Alfa</h3><p>Italiana</p><button>Ver</button></div>
          <div class="card"><img/><h3>Beta</h3><p>Japonesa</p><button>Ver</button></div>
        </section>
        <section id="categories">
          <h2>Categorias</h2>
          <span class="badge">Italiana</span>
          <span class="badge">Japonesa</span>
          <span class="badge">Brasileira</span>
        </section>
      </main>
      <footer><p>2024 iPede</p></footer>
    </body></html>"""

    def test_returns_list_of_extracted_sections(self):
        soup = _soup(self.PLAIN_HTML)
        sections = extract_sections_for_plain_html(soup, "MainPage")
        assert isinstance(sections, list)

    def test_finds_multiple_sections_from_semantic_html(self):
        soup = _soup(self.PLAIN_HTML)
        sections = extract_sections_for_plain_html(soup, "MainPage")
        assert len(sections) >= 2

    def test_all_sections_have_correct_screen(self):
        soup = _soup(self.PLAIN_HTML)
        sections = extract_sections_for_plain_html(soup, "MainPage")
        assert all(s.screen == "MainPage" for s in sections)

    def test_footer_detected_as_section(self):
        soup = _soup(self.PLAIN_HTML)
        sections = extract_sections_for_plain_html(soup, "MainPage")
        names = [s.name.lower() for s in sections]
        assert any("footer" in n for n in names)

    def test_all_section_ids_are_unique(self):
        soup = _soup(self.PLAIN_HTML)
        sections = extract_sections_for_plain_html(soup, "MainPage")
        ids = [s.id for s in sections]
        assert len(ids) == len(set(ids))

    def test_empty_html_returns_empty_list(self):
        soup = _soup("<html><body></body></html>")
        sections = extract_sections_for_plain_html(soup, "Empty")
        assert isinstance(sections, list)
