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
