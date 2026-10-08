"""
A component is defined once, with slots where its occurrences differ; each
screen keeps a skeleton where every occurrence is an instance tag carrying
its slot values — and expanding the skeleton gives the page back.
"""

import asyncio

from bs4 import BeautifulSoup

from design_graph.capture.base import PrototypeDocument
from design_graph.capture.dc_canvas.instances import expand_skeleton
from design_graph.capture.registry import capture_for
from tests.support.dc_canvas import Page, canvas_html


def _footer(n):
    return (f'<footer style="border-top: 1px solid var(--rule)"><div>Sobre estas estimativas</div>'
            f'<a href="A0{n}-Pagina.dc.html">Página {n}</a></footer>')


def _page(n):
    return Page(f"{n} · Tela {n}", f'<div style="display: flex"><main><h1>Tela {n}</h1><p>Texto {n}</p>{_footer(n)}</main></div>')


def _capture(tmp_path):
    path = tmp_path / "canvas.html"
    pages = [_page(1), _page(2), _page(3)]
    path.write_text(canvas_html(pages))
    document = PrototypeDocument.read(path)
    return pages, asyncio.run(capture_for(document).capture(document, concurrency=1))


def _dom(markup):
    return str(BeautifulSoup(markup, "html.parser"))


def test_what_varies_between_occurrences_becomes_a_slot(tmp_path):
    _, result = _capture(tmp_path)
    footer = next(c for c in result.components if c.name == "Footer")
    assert "Sobre estas estimativas" in footer.source_code
    assert 'href="{{slot.href}}"' in footer.source_code and "{{slot.texto}}" in footer.source_code
    assert [(p.prop_name, p.default_value) for p in footer.props] == [("href", "A01-Pagina.dc.html"), ("texto", "Página 1")]


def test_each_occurrence_is_an_instance_in_the_screen_skeleton(tmp_path):
    _, result = _capture(tmp_path)
    second = next(s for s in result.screens if s.name == "Tela 2")
    assert '<Footer href="A02-Pagina.dc.html" texto="Página 2"></Footer>' in second.skeleton
    assert "Sobre estas estimativas" not in second.skeleton
    assert "<h1>Tela 2</h1>" in second.skeleton


def test_expanding_the_skeleton_gives_the_page_back(tmp_path):
    pages, result = _capture(tmp_path)
    templates = {c.name: c.source_code for c in result.components}
    for page, screen in zip(pages, result.screens):
        assert _dom(expand_skeleton(screen.skeleton, templates)).count(_dom(page.body)) == 1


def test_an_instance_named_like_an_html_tag_never_swallows_the_real_tag():
    templates = {"Footer": '<footer class="x"><a href="{{slot.href}}">{{slot.texto}}</a></footer>'}
    skeleton = '<main><footer>literal</footer><Footer href="a.html" texto="Ir &amp; voltar"></Footer></main>'
    assert _dom(expand_skeleton(skeleton, templates)) == _dom(
        '<main><footer>literal</footer><footer class="x"><a href="a.html">Ir &amp; voltar</a></footer></main>'
    )


def test_only_the_style_properties_that_vary_become_slots():
    from design_graph.capture.dc_canvas.instances import definition_of, slot_marker

    cells = BeautifulSoup(
        "".join(f'<div style="width: 24px;  background: {color}; border-radius: 4px">{n}</div>'
                for n, color in enumerate(["#e8f1ef", "#0d5c63", "#5fb0b0"])),
        "html.parser",
    ).find_all("div")
    definition = definition_of(cells)
    assert definition.markup == (
        f'<div style="width: 24px;  background: {slot_marker("background")}; border-radius: 4px">{slot_marker("texto")}</div>'
    )
    assert definition.values[id(cells[1])] == {"background": "#0d5c63", "texto": "1"}
    skeleton = '<main><Cell background="#0d5c63" texto="1"></Cell></main>'
    assert _dom(expand_skeleton(skeleton, {"Cell": definition.markup})) == _dom(f"<main>{cells[1]}</main>")


def test_a_styled_cell_repeated_within_one_page_is_a_component(tmp_path):
    cells = "".join(
        f'<div style="width: 24px; background: {color}; border-radius: 4px">{n}</div>'
        for n, color in enumerate(["#e8f1ef", "#0d5c63", "#5fb0b0", "#e8f1ef"])
    )
    path = tmp_path / "canvas.html"
    path.write_text(canvas_html([Page("1 · Mapa", f'<main><h1>Mapa</h1><section style="display: grid">{cells}</section></main>')]))
    document = PrototypeDocument.read(path)
    result = asyncio.run(capture_for(document).capture(document, concurrency=1))
    cell = next(c for c in result.components if "{{slot.background}}" in c.source_code)
    assert cell.occurrence == 4
    assert result.screens[0].skeleton.count(f"<{cell.name} ") == 4


def test_styles_written_differently_never_share_a_template():
    from design_graph.capture.dc_canvas.instances import definition_of

    cells = BeautifulSoup(
        '<i style="fill: red; stroke: 1;">a</i><i style="fill: blue; stroke: 1">b</i><i style="fill: green; stroke: 1">c</i>',
        "html.parser",
    ).find_all("i")
    definition = definition_of(cells)
    assert set(definition.values) == {id(cells[1]), id(cells[2])}  # the trailing-";" one stays literal


def test_authoring_hints_of_the_canvas_editor_are_not_part_of_a_component_or_screen(tmp_path):
    import asyncio

    from design_graph.capture.base import PrototypeDocument
    from design_graph.capture.registry import capture_for
    from tests.support.dc_canvas import Page, canvas_html

    def page(n: int, count: int) -> Page:
        return Page(f"{n} · Pergunta {n}", (
            f'<main><div style="display: flex; gap: 8px"><sc-for list="{{{{xs}}}}" as="o" hint-placeholder-count="{count}">'
            '<button type="button"><span>{{o.label}}</span></button></sc-for></div>'
            f'<sc-if value="{{{{open}}}}" hint-placeholder-val="{{{{true}}}}"><p>Aberto {n}</p></sc-if></main>'
        ))

    path = tmp_path / "canvas.html"
    path.write_text(canvas_html([page(1, 5), page(2, 3), page(3, 2)]))
    document = PrototypeDocument.read(path)
    result = asyncio.run(capture_for(document).capture(document, concurrency=1))
    assert result.components
    for component in result.components:
        assert "hint-placeholder" not in component.source_code
        assert not [p for p in component.props if p.prop_name.startswith("hint-")]
    assert all("hint-placeholder" not in screen.skeleton for screen in result.screens)
