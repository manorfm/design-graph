"""A DC canvas's design tokens: custom properties per mode, font families and repeated literals."""

from __future__ import annotations

import asyncio

from design_graph.capture.base import PrototypeDocument
from design_graph.capture.registry import capture_for
from tests.support.dc_canvas import Page, canvas_html

THEMES = ".tc{--accent:#0D5C63;--ink:#1E1C19}\n.te{--accent:#5FB0B0;--ink:#EDE8DF}\n:root{--gap:8px}"
TEMA = {"tema": {"editor": "enum", "options": ["claro", "escuro"], "default": "claro"}}
BODY = (
    '<div class="{{t}}" style="color: var(--ink); font-family:\'IBM Plex Sans\', sans-serif; font-size: 15px">'
    '<p style="color: var(--accent); font-size: 15px">Olá</p>'
    '<span style="border: 1px solid var(--accent)">x</span></div>'
)


def _tokens(tmp_path, pages):
    path = tmp_path / "canvas.html"
    path.write_text(canvas_html(pages))
    document = PrototypeDocument.read(path)
    return asyncio.run(capture_for(document).capture(document, concurrency=1)).tokens


def _page(title="1 · A", logic=None):
    kwargs = {"logic": logic} if logic else {}
    return Page(title, BODY, helmet_css=THEMES, props=TEMA, **kwargs)


def _custom(tokens):
    return {(t.label, t.mode): t for t in tokens if t.category == "css_var"}


class TestCustomPropertiesByMode:
    def test_each_theme_selector_becomes_a_mode_of_the_enum_prop(self, tmp_path):
        tokens = _custom(_tokens(tmp_path, [_page()]))
        assert tokens[("--accent", "claro")].value == "#0D5C63"
        assert tokens[("--accent", "escuro")].value == "#5FB0B0"

    def test_logic_that_names_the_theme_class_decides_the_mode(self, tmp_path):
        logic = "class Component extends DCLogic { renderVals() { const t = tema === 'escuro' ? 'tc' : 'te'; } }"
        tokens = _custom(_tokens(tmp_path, [_page(logic=logic)]))
        assert tokens[("--accent", "escuro")].value == "#0D5C63"

    def test_root_properties_belong_to_every_mode(self, tmp_path):
        assert _custom(_tokens(tmp_path, [_page()]))[("--gap", "")].value == "8px"

    def test_tokens_repeated_on_every_page_are_captured_once(self, tmp_path):
        tokens = [t for t in _tokens(tmp_path, [_page("1 · A"), _page("2 · B")]) if t.category == "css_var"]
        assert len(tokens) == 5

    def test_usage_counts_every_reference_across_pages(self, tmp_path):
        tokens = _custom(_tokens(tmp_path, [_page("1 · A"), _page("2 · B")]))
        assert tokens[("--accent", "claro")].usage == 4

    def test_selectors_without_a_matching_enum_keep_their_own_name_as_mode(self, tmp_path):
        page = Page("1 · A", BODY, helmet_css=".light{--accent:#fff}\n.dark{--accent:#000}\n.hc{--accent:#ff0}", props={})
        assert {mode for _, mode in _custom(_tokens(tmp_path, [page]))} == {"light", "dark", "hc"}


class TestOtherTokens:
    def test_font_family_of_the_page_is_a_typography_token(self, tmp_path):
        tokens = _tokens(tmp_path, [_page()])
        assert any(t.category == "typography" and t.value == "IBM Plex Sans" for t in tokens)

    def test_repeated_literal_values_become_tokens(self, tmp_path):
        tokens = _tokens(tmp_path, [_page("1 · A"), _page("2 · B")])
        assert any(t.category == "typography" and t.value == "15px" for t in tokens)
