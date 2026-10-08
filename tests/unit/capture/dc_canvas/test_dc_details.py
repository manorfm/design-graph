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

    def test_an_item_repeated_by_several_lists_carries_each_of_them(self, tmp_path):
        item = _components(tmp_path, [LOOP_PAGE, _second_question("3 · Tempo", "tem", "Semanas")])["PapelItem"]
        assert item.referenced_data == {
            "papel": [{"id": "dir", "label": "Direção executiva"}, {"id": "eng", "label": "Engenharia"}],
            "tem": [{"id": "a", "label": "Semanas"}],
        }

    def test_a_list_named_alike_on_another_screen_with_other_values_is_kept_apart(self, tmp_path):
        pages = [LOOP_PAGE, _second_question("3 · Outra pergunta", "papel", "Produto")]
        item = _components(tmp_path, pages)["PapelItem"]
        assert item.referenced_data["papel"][0]["label"] == "Direção executiva"
        assert item.referenced_data["papel · Outra pergunta"] == [{"id": "a", "label": "Produto"}]

    def test_the_same_list_on_two_screens_is_carried_once(self, tmp_path):
        pages = [LOOP_PAGE, Page("3 · Sua perspectiva (web)", LOOP_PAGE.body, logic=LOOP_PAGE.logic)]
        assert list(_components(tmp_path, pages)["PapelItem"].referenced_data) == ["papel"]


def _second_question(title: str, list_name: str, label: str) -> Page:
    return Page(
        title,
        f'<div><div role="group"><sc-for list="{{{{{list_name}}}}}" as="o"><button><span>{{{{o.label}}}}</span>'
        "<span>·</span></button></sc-for></div><p>Escolha outra</p></div>",
        logic=f'class Component extends DCLogic {{ renderVals() {{ const {list_name} = [{{"id": "a", "label": "{label}"}}];'
              f" return {{ {list_name} }}; }} }}",
    )


class TestRepresentativeOccurrence:
    """A component's texts, styles and slot defaults all describe one same occurrence."""

    NUMBER = '<div style="font-size: {size}; font-weight: 500; line-height: 1.1"{extra}>{text}</div>'
    PAGES = [
        Page("1 · Laudo", f'<main>{NUMBER.format(size="40px", extra=' title="índice"', text="92")}<p>Laudo</p></main>'),
        Page("2 · Boas-vindas", f'<main>{NUMBER.format(size="20px", extra="", text="Anamnese")}<p>Um</p></main>'),
        Page("3 · Termo", f'<main>{NUMBER.format(size="20px", extra="", text="Termo de uso")}<p>Dois</p></main>'),
    ]

    def _number(self, tmp_path):
        return next(c for c in _components(tmp_path, self.PAGES).values() if "font-weight: 500" in c.source_code)

    def test_texts_come_from_the_occurrence_the_template_is_made_of(self, tmp_path):
        number = self._number(tmp_path)
        defaults = {p.prop_name: p.default_value for p in number.props}
        assert [t.content for t in number.texts] == [defaults["texto"]] == ["Anamnese"]

    def test_styles_come_from_that_occurrence_too(self, tmp_path):
        sizes = {s.value for s in self._number(tmp_path).styles if s.property == "font-size"}
        assert sizes == {"20px"}


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
