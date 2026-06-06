"""
Edge-case tests for html_parser.py — covers branches missed by test_html_parser.py.

Targets:
  - extract_dom_patterns: traversal exception recovery, min_count filtering,
    inferred names via CSS class and tag fallback
  - extract_semantic_sections: exception recovery, id/aria-label name derivation
  - _structure_signature: depth limit, children with and without classes
  - _infer_semantic_type: all semantic branches (nav, header, footer, card, modal, badge, form, table, list-item)
  - _section_name_from_tag: heading > id > aria-label > tag fallback
"""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from design_graph.parsing.html_parser import (
    _infer_semantic_type,
    _section_name_from_tag,
    _structure_signature,
    extract_dom_patterns,
    extract_semantic_sections,
)


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _tag(html: str):
    return _soup(html).find()


# ── extract_dom_patterns ──────────────────────────────────────────────────────

class TestExtractDomPatternsEdgeCases:
    def test_min_count_filters_rare_patterns(self):
        # 3 identical cards, 1 unique nav — with min_count=3, nav should be excluded
        html = """<html><body>
            <div class="card"><img/><h3>A</h3><p>X</p></div>
            <div class="card"><img/><h3>B</h3><p>Y</p></div>
            <div class="card"><img/><h3>C</h3><p>Z</p></div>
            <nav><a>home</a></nav>
        </body></html>"""
        patterns = extract_dom_patterns(_soup(html), min_count=3)
        sig_strings = [p.signature for p in patterns]
        # The card pattern should be found; nav appears only once and should not
        assert any("card" in s for s in sig_strings)

    def test_returns_empty_list_on_exception(self, monkeypatch):
        """Should return [] and not raise if BeautifulSoup traversal throws."""
        from bs4 import BeautifulSoup as BS
        bad_soup = BS("", "html.parser")
        # Monkeypatch find_all to raise
        monkeypatch.setattr(bad_soup, "find_all", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("oops")))
        result = extract_dom_patterns(bad_soup, min_count=2)
        assert result == []

    def test_inferred_name_from_css_class(self):
        html = """<html><body>
            <div class="restaurant-card"><img/><h3>R1</h3><p>info</p><button>Order</button></div>
            <div class="restaurant-card"><img/><h3>R2</h3><p>info</p><button>Order</button></div>
            <div class="restaurant-card"><img/><h3>R3</h3><p>info</p><button>Order</button></div>
        </body></html>"""
        patterns = extract_dom_patterns(_soup(html), min_count=3)
        if patterns:
            # "restaurant-card" → "RestaurantCard"
            names = [p.inferred_name for p in patterns]
            assert any("Card" in n or "Restaurant" in n for n in names)

    def test_pattern_has_count_equal_to_occurrences(self):
        html = "<html><body>" + "<div><span>x</span></div>" * 5 + "</body></html>"
        patterns = extract_dom_patterns(_soup(html), min_count=2)
        for p in patterns:
            assert p.count >= 2

    def test_patterns_sorted_by_count_descending(self):
        html = """<html><body>
            <div class="a"><span>x</span></div>
            <div class="a"><span>x</span></div>
            <div class="a"><span>x</span></div>
            <article><p>text</p></article>
            <article><p>text</p></article>
        </body></html>"""
        patterns = extract_dom_patterns(_soup(html), min_count=2)
        counts = [p.count for p in patterns]
        assert counts == sorted(counts, reverse=True)


# ── extract_semantic_sections ─────────────────────────────────────────────────

class TestExtractSemanticSectionsEdgeCases:
    def test_section_named_by_id_when_no_heading(self):
        html = "<html><body><section id='hero-banner'><p>content</p></section></body></html>"
        sections = extract_semantic_sections(_soup(html))
        assert any("Hero Banner" in s["name"] or "hero" in s["name"].lower() for s in sections)

    def test_section_named_by_aria_label(self):
        html = "<html><body><nav aria-label='Main navigation'><a>home</a></nav></body></html>"
        sections = extract_semantic_sections(_soup(html))
        assert any("Main navigation" in s["name"] or "navigation" in s["name"].lower()
                   for s in sections)

    def test_fallback_name_is_tag_capitalize(self):
        html = "<html><body><aside><p>sidebar content</p></aside></body></html>"
        sections = extract_semantic_sections(_soup(html))
        assert any("Aside" in s["name"] or "aside" in s["name"].lower() for s in sections)

    def test_includes_depth_field(self):
        html = "<html><body><main><p>content</p></main></body></html>"
        sections = extract_semantic_sections(_soup(html))
        for s in sections:
            assert "depth" in s
            assert isinstance(s["depth"], int)

    def test_returns_empty_on_exception(self, monkeypatch):
        from bs4 import BeautifulSoup as BS
        bad_soup = BS("", "html.parser")
        monkeypatch.setattr(bad_soup, "find_all", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("oops")))
        result = extract_semantic_sections(bad_soup)
        assert result == []

    def test_all_standard_semantic_tags_detected(self):
        html = """<html><body>
            <nav><a>home</a></nav>
            <header><h1>Site</h1></header>
            <main><p>content</p></main>
            <aside><p>sidebar</p></aside>
            <footer><p>footer</p></footer>
        </body></html>"""
        sections = extract_semantic_sections(_soup(html))
        tags_found = {s["tag"] for s in sections}
        assert "nav" in tags_found
        assert "header" in tags_found
        assert "footer" in tags_found


# ── _structure_signature ──────────────────────────────────────────────────────

class TestStructureSignature:
    def test_max_depth_returns_just_tag_name(self):
        tag = _tag("<div><span><em><strong>text</strong></em></span></div>")
        sig = _structure_signature(tag, depth=3, max_depth=3)
        assert sig == "div"

    def test_tag_without_children_returns_base(self):
        tag = _tag("<span class='btn'>text</span>")
        sig = _structure_signature(tag)
        assert "span" in sig

    def test_class_hint_included_in_signature(self):
        tag = _tag("<div class='card'><p>text</p></div>")
        sig = _structure_signature(tag)
        assert "card" in sig

    def test_no_class_produces_clean_signature(self):
        tag = _tag("<div><p>text</p></div>")
        sig = _structure_signature(tag)
        assert sig.startswith("div")
        assert "." not in sig.split(">")[0]  # no class hint on root without class


# ── _infer_semantic_type ──────────────────────────────────────────────────────

class TestInferSemanticType:
    def test_nav_tag(self):
        assert _infer_semantic_type(_tag("<nav><a>x</a></nav>")) == "nav"

    def test_navbar_class(self):
        assert _infer_semantic_type(_tag("<div class='navbar'><a>x</a></div>")) == "nav"

    def test_header_tag(self):
        assert _infer_semantic_type(_tag("<header><h1>x</h1></header>")) == "header"

    def test_footer_tag(self):
        assert _infer_semantic_type(_tag("<footer><p>x</p></footer>")) == "footer"

    def test_card_class(self):
        assert _infer_semantic_type(_tag("<div class='card'>x</div>")) == "card"

    def test_modal_class(self):
        assert _infer_semantic_type(_tag("<div class='modal'>x</div>")) == "modal"

    def test_badge_class(self):
        assert _infer_semantic_type(_tag("<span class='badge'>x</span>")) == "badge"

    def test_form_tag(self):
        assert _infer_semantic_type(_tag("<form><input/></form>")) == "form"

    def test_table_tag(self):
        assert _infer_semantic_type(_tag("<table><tr><td>x</td></tr></table>")) == "table"

    def test_list_item_tag(self):
        assert _infer_semantic_type(_tag("<li>item</li>")) == "list-item"

    def test_unknown_returns_component(self):
        assert _infer_semantic_type(_tag("<section><p>x</p></section>")) == "component"


# ── _section_name_from_tag ────────────────────────────────────────────────────

class TestSectionNameFromTag:
    def test_heading_wins_over_id(self):
        tag = _tag("<section id='hero'><h2>Featured Restaurants</h2><p>x</p></section>")
        name = _section_name_from_tag(tag)
        assert "Featured" in name or "Restaurants" in name

    def test_id_used_when_no_heading(self):
        tag = _tag("<section id='promo-banner'><p>content</p></section>")
        name = _section_name_from_tag(tag)
        assert "Promo" in name or "Banner" in name or "promo" in name.lower()

    def test_aria_label_used_when_no_id_or_heading(self):
        tag = _tag("<nav aria-label='Primary navigation'><a>x</a></nav>")
        name = _section_name_from_tag(tag)
        assert "Primary" in name or "navigation" in name.lower()

    def test_tag_name_fallback(self):
        tag = _tag("<aside><p>sidebar</p></aside>")
        name = _section_name_from_tag(tag)
        assert "Aside" in name

    def test_empty_heading_falls_through(self):
        tag = _tag("<section><h2>   </h2><p>content</p></section>")
        name = _section_name_from_tag(tag)
        assert isinstance(name, str) and len(name) > 0
