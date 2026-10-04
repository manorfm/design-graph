"""Loop data, pseudo-class states and fragment reading of the DC capture."""

from __future__ import annotations

import asyncio

import pytest

from design_graph.capture.base import PrototypeDocument
from design_graph.capture.registry import capture_for, capture_named
from tests.support.dc_canvas import Page, canvas_html

LOOP_PAGE = Page(
    "2 · Sua perspectiva",
    '<div><div role="group"><sc-for list="{{papel}}" as="o"><button><span>{{o.label}}</span><span>·</span>'
    '</button></sc-for></div><p>Escolha uma</p></div>',
    logic=(
        "class Component extends DCLogic {\n  renderVals() {\n"
        '    const papel = [{"id": "dir", "label": "Direção executiva"}, {"id": "eng", "label": "Engenharia"}]'
        ".map((o) => ({ ...o, pick: () => this.setState({ papel: o.id }) }));\n"
        "    return { papel };\n  }\n}"
    ),
)
LINK_PAGES = [
    Page(f"{n} · Tela {n}", f'<div><a href="#x" style="color: var(--accent-ink)">Saiba mais</a><p>Texto {n}</p></div>',
         helmet_css="a{color:var(--accent-ink)}a:hover{color:var(--ink)}\nbutton:focus{outline:2px solid red}")
    for n in (1, 2, 3)
]


def _components(tmp_path, pages):
    path = tmp_path / "canvas.html"
    path.write_text(canvas_html(pages))
    document = PrototypeDocument.read(path)
    result = asyncio.run(capture_for(document).capture(document, concurrency=1))
    return {c.name: c for c in result.components}


class TestLoopData:
    def test_loop_item_carries_the_literal_list_it_repeats(self, tmp_path):
        item = _components(tmp_path, [LOOP_PAGE])["PapelItem"]
        assert item.referenced_data == {"papel": [
            {"id": "dir", "label": "Direção executiva"}, {"id": "eng", "label": "Engenharia"},
        ]}

    def test_list_that_is_not_a_literal_is_left_out(self, tmp_path):
        page = Page(LOOP_PAGE.title, LOOP_PAGE.body, logic="class Component extends DCLogic { renderVals() {"
                    " const papel = load(); return { papel }; } }")
        assert _components(tmp_path, [page])["PapelItem"].referenced_data == {}


class TestPseudoClassStates:
    def test_tag_hover_rule_of_the_page_styles_the_component(self, tmp_path):
        link = _components(tmp_path, LINK_PAGES)["SaibaMaisLink"]
        hover = {(s.property, s.value) for s in link.styles if s.state == "hover"}
        assert hover == {("color", "var(--ink)")}

    def test_rules_for_other_tags_do_not_apply(self, tmp_path):
        link = _components(tmp_path, LINK_PAGES)["SaibaMaisLink"]
        assert all(s.state != "focus" for s in link.styles)


class TestFragment:
    def test_fragment_yields_its_styles_texts_and_language(self):
        comp = capture_named("dc_canvas").capture_fragment('<a style="color: var(--accent)">Começar agora</a>')
        assert ("color", "var(--accent)") in {(s.property, s.value) for s in comp.styles}
        assert "Começar agora" in {t.content for t in comp.texts}
        assert comp.source_lang == "html-template"

    @pytest.mark.parametrize("source", ["", "   ", "just text"])
    def test_fragment_without_an_element_yields_nothing(self, source):
        assert capture_named("dc_canvas").capture_fragment(source) is None
