"""A DC canvas is recognized as its own format and every board becomes a screen."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from design_graph.capture.base import PrototypeDocument
from design_graph.capture.registry import capture_for
from tests.support.dc_canvas import Page, canvas_html

FIXTURES = Path(__file__).parents[3] / "fixtures"


def _document(tmp_path, text: str, name: str = "canvas.html") -> PrototypeDocument:
    path = tmp_path / name
    path.write_text(text)
    return PrototypeDocument.read(path)


def _capture(document):
    return asyncio.run(capture_for(document).capture(document, concurrency=2))


PAGES = [
    Page("1 · Boas-vindas", "<main><h1>Olá</h1></main>"),
    Page("2 · Sua perspectiva", "<main><h1>Quem é você</h1></main>"),
    Page("1 · Boas-vindas (desktop)", "<main><h1>Olá</h1></main>", width=1280, height=800),
]


class TestRecognition:
    def test_canvas_is_captured_as_dc_canvas(self, tmp_path):
        assert capture_for(_document(tmp_path, canvas_html(PAGES))).name == "dc_canvas"

    def test_react_bundle_is_still_an_html_prototype(self):
        document = PrototypeDocument.read(FIXTURES / "simple.html")
        assert capture_for(document).name == "html_prototype"

    def test_bundle_without_boards_is_not_a_canvas(self, tmp_path):
        text = canvas_html(PAGES).replace('<section class=\\"board\\">', "<div>")
        text = text.replace("about:blank#", "https://example.com/#")
        assert capture_for(_document(tmp_path, text)).name == "html_prototype"


class TestBoardsBecomeScreens:
    def test_one_screen_per_board_named_without_its_number(self, tmp_path):
        result = _capture(_document(tmp_path, canvas_html(PAGES)))
        assert result.capture == "dc_canvas"
        assert [s.name for s in result.screens] == ["Boas-vindas", "Sua perspectiva", "Boas-vindas (desktop)"]

    def test_screen_keeps_the_board_viewport(self, tmp_path):
        desktop = _capture(_document(tmp_path, canvas_html(PAGES))).screens[2]
        assert (desktop.viewport_width, desktop.viewport_height) == (1280, 800)

    def test_undecodable_page_is_skipped_and_counted(self, tmp_path):
        text = canvas_html(PAGES)
        broken = text.replace('"compressed": true, "data": "', '"compressed": true, "data": "!!', 1)
        result = _capture(_document(tmp_path, broken))
        assert result.skipped_entries == 1
        assert len(result.screens) == 2

    def test_duplicate_board_titles_stay_distinct_screens(self, tmp_path):
        pages = [Page("1 · Laudo", "<main>a</main>"), Page("2 · Laudo", "<main>b</main>")]
        names = [s.name for s in _capture(_document(tmp_path, canvas_html(pages))).screens]
        assert len(set(names)) == 2
