"""Each DC page splits into the blocks a reader sees, each with its texts and own styles."""

from __future__ import annotations

import asyncio

from design_graph.capture.base import PrototypeDocument
from design_graph.capture.registry import capture_for
from tests.support.dc_canvas import Page, canvas_html

MOBILE = """
<div class="{{t}}" style="width: 390px"><div style="display: flex; flex-direction: column">
  <div style="padding: 20px 24px 0 24px"><span>Anamnese de Tecnologia</span><span>cerca de 14 min</span></div>
  <div style="gap: 20px; background: {{o.bg}}"><h2>Como o trabalho acontece</h2>
    <p>Este questionário ajuda a entender.</p>
    <sc-for list="{{papel}}" as="o"><button>{{o.label}}</button></sc-for></div>
  <div aria-label="Ações"><a href="A02-Perspectiva.dc.html">Começar agora</a></div>
</div></div>
"""

DESKTOP = """
<div class="{{t}}" style="display: flex">
  <aside style="width: 248px"><nav><a href="C13-Laudo.dc.html">Laudo</a></nav></aside>
  <main style="padding: 40px">
    <header><h1>Mapa navegável</h1></header>
    <div><sc-raw-table><sc-raw-tr><sc-raw-td>Fluxo de entrega</sc-raw-td></sc-raw-tr></sc-raw-table></div>
    <footer><div>Sobre estas estimativas</div></footer>
  </main>
</div>
"""


def _sections(tmp_path, body, title="1 · Tela"):
    path = tmp_path / "canvas.html"
    path.write_text(canvas_html([Page(title, body)]))
    document = PrototypeDocument.read(path)
    result = asyncio.run(capture_for(document).capture(document, concurrency=1))
    return result.sections[title.split(" · ", 1)[1]]


class TestBlocks:
    def test_page_splits_into_its_top_level_blocks(self, tmp_path):
        names = [s.name for s in _sections(tmp_path, MOBILE)]
        assert names == ["Anamnese de Tecnologia", "Como o trabalho acontece", "Ações"]

    def test_main_area_is_split_and_semantic_blocks_are_named_by_role(self, tmp_path):
        names = [s.name for s in _sections(tmp_path, DESKTOP)]
        assert names == ["Sidebar", "Mapa navegável", "Fluxo de entrega", "Footer"]

    def test_semantic_blocks_are_detected_semantically(self, tmp_path):
        methods = {s.name: s.detection_method for s in _sections(tmp_path, DESKTOP)}
        assert methods["Sidebar"] == "semantic" and methods["Fluxo de entrega"] == "structural"


class TestBlockContent:
    def test_texts_are_the_visible_copy_without_interpolations(self, tmp_path):
        block = _sections(tmp_path, MOBILE)[1]
        assert block.texts == ["Como o trabalho acontece", "Este questionário ajuda a entender."]

    def test_styles_are_the_block_own_literal_declarations(self, tmp_path):
        assert _sections(tmp_path, MOBILE)[0].styles == {"padding": "20px 24px 0 24px"}
        assert "background" not in _sections(tmp_path, MOBILE)[1].styles

    def test_source_keeps_the_dc_directives_as_written(self, tmp_path):
        block = _sections(tmp_path, MOBILE)[1]
        assert '<sc-for as="o" list="{{papel}}">' in block.source_code or '<sc-for list="{{papel}}" as="o">' in block.source_code
        assert block.source_lang == "html-template"

    def test_raw_table_cells_are_read_as_table_cells(self, tmp_path):
        table = next(s for s in _sections(tmp_path, DESKTOP) if s.name == "Fluxo de entrega")
        assert table.texts == ["Fluxo de entrega"]

    def test_block_names_are_unique_within_a_screen(self, tmp_path):
        body = '<div><div><p>Mesmo texto</p></div><div><p>Mesmo texto</p></div></div>'
        names = [s.name for s in _sections(tmp_path, body)]
        assert len(names) == len(set(names)) == 2


class TestBlockNames:
    def test_numbers_and_symbols_never_name_a_block(self, tmp_path):
        body = '<div><div><span>60%+</span><span>100</span><p>Engenharia por domínio</p></div><div><p>B</p></div></div>'
        assert _sections(tmp_path, body)[0].name == "Engenharia por domínio"

    def test_long_names_are_cut_at_a_word_boundary(self, tmp_path):
        body = '<div><div><h2>Como o trabalho acontece de verdade por aqui hoje</h2></div><div><p>Fim do bloco</p></div></div>'
        assert _sections(tmp_path, body)[0].name == "Como o trabalho acontece de verdade por…"


class TestEveryVisibleTextIsKept:
    def test_long_paragraphs_lowercase_labels_and_symbols_are_copy(self, tmp_path):
        paragraph = "Em vez de opiniões gerais, vamos pedir que você pense em casos reais e recentes: o último deploy."
        body = f"<div><div><p>{paragraph}</p><span>gera</span><span>·</span></div><div><p>Fim</p></div></div>"
        texts = _sections(tmp_path, body)[0].texts
        assert texts == [paragraph, "gera", "·"]


class TestEveryElementStyle:
    BLOCK = (
        '<div style="padding: 8px"><h2 style="font-size: 38px">Título</h2>'
        '<ul><li>a</li><li><span style="color: red">b</span></li></ul></div>'
    )

    def test_root_styles_stay_the_section_own_and_descendants_keep_their_path(self, tmp_path):
        section = _sections(tmp_path, f"<main>{self.BLOCK}<div>outro</div></main>")[0]
        assert section.styles == {"padding": "8px"}
        assert {(s.element, s.property, s.value) for s in section.element_styles} == {
            ("h2", "font-size", "38px"),
            ("ul > li:2 > span", "color", "red"),
        }

    def test_interpolated_values_stay_out(self, tmp_path):
        section = _sections(tmp_path, '<main><div><p style="color: {{o.c}}; margin: 0">x</p></div><div>y</div></main>')[0]
        assert {(s.element, s.property, s.value) for s in section.element_styles} == {("p", "margin", "0")}


class TestPageWrapperStyles:
    def test_the_elements_around_the_blocks_are_the_screen_own_styles(self, tmp_path):
        path = tmp_path / "canvas.html"
        path.write_text(canvas_html([Page("1 · Tela", MOBILE)]))
        document = PrototypeDocument.read(path)
        screen = asyncio.run(capture_for(document).capture(document, concurrency=1)).screens[0]
        assert {(s.element, s.property, s.value) for s in screen.styles} == {
            ("div", "width", "390px"),
            ("div > div", "display", "flex"),
            ("div > div", "flex-direction", "column"),
        }
