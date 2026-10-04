"""Components of a DC canvas are the structures its pages repeat."""

from __future__ import annotations

import asyncio

from design_graph.capture.base import PrototypeDocument
from design_graph.capture.registry import capture_for
from tests.support.dc_canvas import Page, canvas_html

SIDEBAR = (
    '<aside style="width: 248px"><nav style="display: flex">'
    '<a href="C13-Laudo.dc.html" style="background: var(--accent-soft)">Laudo</a>'
    '<a href="C14-Mapa.dc.html" style="color: var(--ink2)">Mapa</a></nav></aside>'
)
FOOTER = '<footer style="border-top: 1px solid var(--rule)"><div>Sobre estas estimativas</div><div>Amostra: 64</div></footer>'
OPTIONS = (
    '<div role="group"><sc-for list="{{papel}}" as="o">'
    '<button type="button" style="border: 1.5px solid {{o.bc}}"><span>{{o.label}}</span><span>·</span></button>'
    '</sc-for></div>'
)


def _page(n: int, main: str) -> Page:
    return Page(f"{n} · Tela {n}", f'<div style="display: flex">{SIDEBAR}<main><h1>Tela {n}</h1>{main}{FOOTER}</main></div>')


def _capture(tmp_path, pages):
    path = tmp_path / "canvas.html"
    path.write_text(canvas_html(pages))
    document = PrototypeDocument.read(path)
    return asyncio.run(capture_for(document).capture(document, concurrency=2))


THREE_PAGES = [_page(1, "<p>Um</p>"), _page(2, "<p>Dois</p>"), _page(3, OPTIONS)]


def _components(tmp_path, pages=THREE_PAGES):
    return {c.name: c for c in _capture(tmp_path, pages).components}


class TestPromotion:
    def test_structure_repeated_on_three_pages_is_a_component(self, tmp_path):
        footer = _components(tmp_path)["Footer"]
        assert footer.occurrence == 3
        assert footer.source_lang == "html-template" and "<footer" in footer.source_code

    def test_structure_on_fewer_pages_is_not(self, tmp_path):
        assert "Footer" not in _components(tmp_path, THREE_PAGES[:2])

    def test_loop_item_is_a_component_even_on_one_page(self, tmp_path):
        item = _components(tmp_path)["PapelItem"]
        assert item.comp_type == "button"

    def test_names_are_unique(self, tmp_path):
        names = [c.name for c in _capture(tmp_path, THREE_PAGES).components]
        assert len(names) == len(set(names))


class TestStructure:
    def test_nested_components_are_its_children_in_order(self, tmp_path):
        components = _components(tmp_path)
        assert components["Sidebar"].child_refs == ["Navigation"]
        assert components["Navigation"].child_refs == ["LaudoLink", "MapaLink"]

    def test_screen_uses_its_outermost_components(self, tmp_path):
        screens = {s.name: s for s in _capture(tmp_path, THREE_PAGES).screens}
        assert screens["Tela 3"].component_refs == ["Sidebar", "PapelItem", "Footer"]

    def test_block_uses_the_components_inside_it(self, tmp_path):
        sections = {s.name: s for s in _capture(tmp_path, THREE_PAGES).sections["Tela 1"]}
        assert sections["Sidebar"].component_refs == ["Sidebar"]
        assert sections["Footer"].component_refs == ["Footer"]


class TestContent:
    def test_styles_are_the_root_literal_declarations(self, tmp_path):
        styles = {(s.property, s.value) for s in _components(tmp_path)["Footer"].styles}
        assert styles == {("border-top", "1px solid var(--rule)")}

    def test_texts_are_typed_by_the_element_showing_them(self, tmp_path):
        link = _components(tmp_path)["LaudoLink"]
        assert [(t.content, t.text_type) for t in link.texts] == [("Laudo", "button")]

    def test_interpolated_values_are_not_styles_or_texts(self, tmp_path):
        item = _components(tmp_path)["PapelItem"]
        assert item.styles == [] and item.texts == []
        assert item.declares_inline_styles is True


class TestInteractiveNames:
    def test_interactive_element_with_the_same_text_everywhere_is_named_by_it(self, tmp_path):
        assert "LaudoLink" in _components(tmp_path)

    def test_interactive_element_whose_text_varies_is_named_by_its_container(self, tmp_path):
        pages = [
            Page(f"{n} · Tela {n}", f'<div><nav aria-label="Relatório"><a style="color: red">Item {n}</a>'
                                    f'<a style="color: blue">Fixo</a></nav><p>Corpo da tela</p></div>')
            for n in (1, 2, 3)
        ]
        components = _components(tmp_path, pages)
        assert components["Relatório"].child_refs == ["RelatórioLink", "FixoLink"]

