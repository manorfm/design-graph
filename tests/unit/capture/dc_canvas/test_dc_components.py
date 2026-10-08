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
        assert item.styles == [] and [text.content for text in item.texts] == ["·"]
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
        assert components["Relatório"].child_refs == ["RelatórioLink"]
        # Links that differ only in their color value are one component, the color a slot.
        assert {p.prop_name for p in components["RelatórioLink"].props} == {"color", "texto"}



class TestEveryElementStyle:
    def test_descendant_styles_are_kept_with_their_path(self, tmp_path):
        sidebar = _components(tmp_path)["Sidebar"]
        assert {(s.element, s.property, s.value) for s in sidebar.styles} >= {
            ("Sidebar", "width", "248px"),
            ("Sidebar > nav", "display", "flex"),
            ("Sidebar > nav > a:1", "background", "var(--accent-soft)"),
            ("Sidebar > nav > a:2", "color", "var(--ink2)"),
        }


class TestReadableNames:
    """A component without a name of its own is named by where it lives and what it is — never by a bare tag or sample copy."""

    HEATMAP = (
        '<main><div aria-label="Perspectivas × capacidades" style="display: grid">'
        + "".join(f'<div style="width: 24px; height: 24px; background: {c}">{n}</div>'
                  for n, c in enumerate(["#e8f1ef", "#0d5c63", "#5fb0b0", "#e8f1ef"]))
        + '</div><section><h2>Radar</h2><svg>'
        + "".join(f'<polygon points="{n},0 1,1" style="fill: red; stroke: blue; stroke-width: 1"></polygon>' for n in range(3))
        + "</svg></section></main>"
    )

    def test_no_component_is_named_after_a_bare_tag(self, tmp_path):
        names = set(_components(tmp_path, [Page("1 · Mapa", self.HEATMAP)]))
        assert not names & {"Div", "Span", "Td", "Polygon", "Rect", "Path", "Line", "A"}

    def test_a_repeated_cell_is_named_by_its_block_and_role(self, tmp_path):
        components = _components(tmp_path, [Page("1 · Mapa", self.HEATMAP)])
        assert "PerspectivasCapacidadesCell" in components

    def test_a_chart_mark_is_named_by_its_block_and_role(self, tmp_path):
        assert "RadarChartMark" in _components(tmp_path, [Page("1 · Mapa", self.HEATMAP)])

    def test_copy_that_varies_never_names_a_component(self, tmp_path):
        cards = "".join(f'<div style="border: 1px solid red"><h3>Projeto {n}</h3><p>descrição</p></div>' for n in range(3))
        names = set(_components(tmp_path, [Page("1 · Lista", f'<main><section aria-label="Projetos">{cards}</section></main>')]))
        assert "ProjetosCard" in names and not any(name.startswith("Projeto0") for name in names)

    def test_the_block_context_skips_little_words(self, tmp_path):
        cells = "".join(f'<div style="width: 24px; height: 24px; background: {c}">{n}</div>'
                        for n, c in enumerate(["#e8f1ef", "#0d5c63", "#5fb0b0"]))
        page = Page("1 · Convites", f'<main><div aria-label="Convites e participação" style="display: grid">{cells}</div><p>x</p></main>')
        assert "ConvitesParticipaçãoCell" in _components(tmp_path, [page])


class TestNamesNeverLeakFromOneScreen:
    """A name comes from what every occurrence shares, never from wherever the first one happens to live."""

    NUMBER = '<div style="font-size: 40px; font-weight: 500; line-height: 1.1">{}</div>'

    def _pages(self, blocks: list[str]) -> list[Page]:
        return [
            Page(f"{n} · Tela {n}", f'<main><section aria-label="{block}">{self.NUMBER.format(n * 10)}<p>Texto {n}</p>'
                                    f"</section><p>Fim</p></main>")
            for n, block in enumerate(blocks, start=1)
        ]

    def _number(self, tmp_path, blocks):
        components = _components(tmp_path, self._pages(blocks))
        return next(name for name, c in components.items() if c.source_code.startswith('<div style="font-size'))

    def test_a_piece_living_in_differently_named_blocks_is_named_by_what_it_is(self, tmp_path):
        assert self._number(tmp_path, ["Convites e participação", "Visão por público", "Laudo"]) == "Tag"

    def test_a_label_that_varies_between_occurrences_does_not_name_the_component(self, tmp_path):
        names = set(_components(tmp_path, self._pages(["Convites e participação", "Visão por público", "Laudo"])))
        assert not any(name.startswith(("Convites", "Visão", "Laudo")) for name in names)

    def test_a_piece_living_in_blocks_named_alike_keeps_that_name(self, tmp_path):
        assert self._number(tmp_path, ["Achados", "Achados", "Achados"]) == "AchadosTag"

    def test_a_loop_item_repeated_by_several_lists_is_not_named_after_one_of_them(self, tmp_path):
        def question(n: int, list_name: str) -> Page:
            return Page(f"{n} · Pergunta {n}", OPTIONS.replace("papel", list_name) + "<p>Escolha</p>")

        names = set(_components(tmp_path, [question(1, "papel"), question(2, "tem")]))
        assert not names & {"PapelItem", "TemItem"}

    def test_an_interactive_element_in_differently_named_containers_is_not_named_after_one(self, tmp_path):
        pages = [
            Page(f"{n} · Tela {n}", f'<div><nav aria-label="{label}"><a style="color: red">Item {n}</a>'
                                    f'<a style="color: blue">Fixo {n}</a></nav><p>Corpo</p></div>')
            for n, label in enumerate(["Relatório", "Cadastro", "Relatório"], start=1)
        ]
        names = set(_components(tmp_path, pages))
        assert not any(name.startswith(("Relatório", "Cadastro")) and name.endswith("Link") for name in names)
