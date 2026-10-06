"""Each DC page says what it loads: the DC runtime, React from its CDN URL, its fonts."""

import asyncio

from design_graph.capture.base import PrototypeDocument
from design_graph.capture.registry import capture_for
from design_graph.model.entities import Certainty, ResourceKind
from tests.support.dc_canvas import FONT_BYTES, REACT_URL, Page, canvas_html


def _capture(tmp_path):
    path = tmp_path / "canvas.html"
    path.write_text(canvas_html([Page("1 · Início", "<div><p>Oi</p></div>"), Page("2 · Fim", "<div><p>Tchau</p></div>")]))
    document = PrototypeDocument.read(path)
    return asyncio.run(capture_for(document).capture(document, concurrency=1))


def test_every_page_lists_runtime_library_and_fonts_once_for_the_whole_canvas(tmp_path):
    result = _capture(tmp_path)
    found = {(r.kind, r.name, r.version, r.origin, r.certainty) for r in result.resources}
    assert found == {
        (ResourceKind.RUNTIME, "dc-runtime", "", "embutido no protótipo", Certainty.STATED),
        (ResourceKind.LIBRARY, "react", "18.3.1", REACT_URL, Certainty.STATED),
        (ResourceKind.FONT, "IBM Plex Sans", "", "embutido no protótipo", Certainty.STATED),
    }
    assert all(set(screen.resource_ids) == {r.id for r in result.resources} for screen in result.screens)


def test_font_bytes_are_counted(tmp_path):
    font = next(r for r in _capture(tmp_path).resources if r.kind == ResourceKind.FONT)
    assert (font.size, font.detail) == (len(FONT_BYTES), "pesos 400 · normal")
