"""Each board's DC page gives its screen a source, its links and, for variants, a base screen."""

from __future__ import annotations

import asyncio

from design_graph.capture.base import PrototypeDocument
from design_graph.capture.registry import capture_for
from tests.support.dc_canvas import Page, canvas_html


def _screens(tmp_path, pages):
    path = tmp_path / "canvas.html"
    path.write_text(canvas_html(pages))
    document = PrototypeDocument.read(path)
    result = asyncio.run(capture_for(document).capture(document, concurrency=2))
    return {s.name: s for s in result.screens}, result


WELCOME = Page(
    "1 · Boas-vindas",
    '<main><h1>Olá</h1><a href="A02-Perspectiva.dc.html">Começar</a><a href="#dados">Dados</a></main>',
    helmet_css=".tc{--accent:#0D5C63}",
    logic="class Component extends DCLogic {\n  renderVals() {\n    return { t: 'tc' };\n  }\n}",
)
PERSPECTIVE = Page(
    "2 · Sua perspectiva",
    '<main><a href="Main.dc.html">Voltar</a><a href="A03-Contexto.dc.html">Continuar</a></main>',
)
WELCOME_DESKTOP = Page("1 · Boas-vindas (desktop)", "<main><h1>Olá</h1></main>", width=1280, height=800)
REPORT = Page("13 · Laudo", "<main>laudo</main>", width=1440, height=4700)
REPORT_DARK = Page(
    "13 · Laudo (tema escuro)", "<main>laudo</main>", width=1440, height=4700,
    props={"tema": {"editor": "enum", "options": ["claro", "escuro"], "default": "escuro"}},
)


class TestScreenSource:
    def test_source_is_the_page_template_with_its_styles_and_logic(self, tmp_path):
        welcome = _screens(tmp_path, [WELCOME])[0]["Boas-vindas"]
        assert welcome.source_lang == "html-template"
        assert "<h1>Olá</h1>" in welcome.source_code
        assert ".tc{--accent:#0D5C63}" in welcome.source_code
        assert "renderVals()" in welcome.source_code

    def test_font_faces_and_bundle_ids_stay_out_of_the_source(self, tmp_path):
        source = _screens(tmp_path, [WELCOME])[0]["Boas-vindas"].source_code
        assert "@font-face" not in source and "url(" not in source

    def test_board_that_is_not_a_dc_page_is_skipped(self, tmp_path):
        path = tmp_path / "c.html"
        path.write_text(canvas_html([Page("1 · Solta", "<main>x</main>", is_dc=False)]))
        document = PrototypeDocument.read(path)
        result = asyncio.run(capture_for(document).capture(document, concurrency=1))
        assert result.screens == [] and result.skipped_entries == 1


class TestNavigation:
    def test_page_links_lead_to_the_boards_their_files_number(self, tmp_path):
        screens, _ = _screens(tmp_path, [WELCOME, PERSPECTIVE, WELCOME_DESKTOP])
        assert [(link.target, link.label) for link in screens["Boas-vindas"].links] == [("Sua perspectiva", "Começar")]

    def test_main_page_is_the_first_board(self, tmp_path):
        screens, _ = _screens(tmp_path, [WELCOME, PERSPECTIVE])
        assert ("Boas-vindas", "Voltar") in [(l.target, l.label) for l in screens["Sua perspectiva"].links]

    def test_link_to_a_page_with_no_board_is_left_out(self, tmp_path):
        screens, _ = _screens(tmp_path, [WELCOME, PERSPECTIVE])
        assert "Continuar" not in [l.label for l in screens["Sua perspectiva"].links]

    def test_variant_board_is_never_a_link_target(self, tmp_path):
        screens, _ = _screens(tmp_path, [WELCOME_DESKTOP, WELCOME, PERSPECTIVE])
        assert ("Boas-vindas", "Voltar") in [(l.target, l.label) for l in screens["Sua perspectiva"].links]


class TestVariants:
    def test_board_at_another_viewport_is_a_viewport_variant(self, tmp_path):
        desktop = _screens(tmp_path, [WELCOME, WELCOME_DESKTOP])[0]["Boas-vindas (desktop)"]
        assert (desktop.variant_of, desktop.variant_axis) == ("Boas-vindas", "viewport")

    def test_board_with_another_default_mode_is_a_mode_variant(self, tmp_path):
        dark = _screens(tmp_path, [REPORT, REPORT_DARK])[0]["Laudo (tema escuro)"]
        assert (dark.variant_of, dark.variant_axis) == ("Laudo", "mode")

    def test_base_screen_is_not_a_variant(self, tmp_path):
        assert _screens(tmp_path, [REPORT, REPORT_DARK])[0]["Laudo"].variant_of == ""

    def test_parenthetical_title_without_a_base_board_is_not_a_variant(self, tmp_path):
        alone = Page("5 · Pressão (rascunho)", "<main/>")
        assert _screens(tmp_path, [alone])[0]["Pressão (rascunho)"].variant_of == ""
