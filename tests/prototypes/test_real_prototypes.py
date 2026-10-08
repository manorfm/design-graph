"""
What an agent needs from a real prototype, checked against the prototype
itself: every screen rebuilds exactly from what the tools return, every
component belongs to a screen, the copy a reader sees can be found, every
screen assembles whole with the lists its logic writes, and a React
prototype's functions come back verbatim.

Real prototypes hold client content and stay out of the repository, so
these checks run only when DG_PROTOTYPES names folders holding them
(`make golden`); anywhere else they are skipped.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import kuzu
import pytest

from design_graph.capture.base import PrototypeDocument
from design_graph.capture.dc_canvas.instances import expand_skeleton
from design_graph.capture.dc_canvas.logic import literal_lists
from design_graph.interface.mcp.tools import ToolDispatcher
from design_graph.model.graph.reader import GraphReader
from design_graph.pipeline.coordinator import run_pipeline

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from context_benchmark import round_trip  # noqa: E402
from prototype_truth import dc_pages, rendering_difference, visible_texts  # noqa: E402

PROTOTYPES = sorted(
    path
    for folder in os.environ.get("DG_PROTOTYPES", "").split(os.pathsep) if folder.strip()
    for path in Path(folder).expanduser().glob("*.html")
)
pytestmark = pytest.mark.skipif(not PROTOTYPES, reason="set DG_PROTOTYPES to folders of real prototypes")

_SEARCHED_TEXTS = 40  # texts searched through the tool, spread over all of them; the rest are checked in the index
_RE_LOOP = re.compile(r"""\blist\s*=\s*["']\{\{\s*([A-Za-z_$][\w$]*)\s*\}\}["']""")


@pytest.fixture(scope="module", params=PROTOTYPES, ids=lambda path: path.stem)
def built(request, tmp_path_factory):
    folder = tmp_path_factory.mktemp("prototype")
    stats = asyncio.run(run_pipeline(request.param, folder / "graph.db", folder / "graph.db.state.json"))
    reader = GraphReader(kuzu.Connection(kuzu.Database(str(folder / "graph.db"), read_only=True)))
    document = PrototypeDocument.read(request.param)
    capture = reader.model_info()["capture"]
    return SimpleNamespace(
        document=document, reader=reader, stats=stats, capture=capture,
        tools=ToolDispatcher([("prototype", reader)]),
        pages=dc_pages(document) if capture == "dc_canvas" else {},
    )


def _canvas_only(built) -> None:
    if built.capture != "dc_canvas":
        pytest.skip("only a DC canvas holds its pages' markup statically")


def test_the_build_writes_everything(built):
    assert built.stats is not None and built.stats.write_errors == 0


def test_every_screen_rebuilds_exactly_from_what_the_tools_return(built):
    _canvas_only(built)
    templates = {c["c.name"]: (built.reader.get_full_source(c["c.name"]) or {}).get("source_code", "")
                 for c in built.reader.list_components()}
    differences = {}
    for name, page in built.pages.items():
        assembly = built.reader.get_screen_assembly(name)
        difference = rendering_difference(expand_skeleton(assembly["skeleton"], templates), page.markup) \
            if assembly else "no assembly"
        if difference:
            differences[name] = difference
    assert not differences, differences


def test_every_component_belongs_to_a_screen(built):
    _canvas_only(built)
    loose = [c["c.name"] for c in built.reader.list_components()
             if not built.reader.find_screens_using_comp_transitively(c["c.name"])]
    assert not loose, f"{len(loose)} components no screen reaches: {loose}"


def test_the_copy_a_reader_sees_can_be_found(built):
    _canvas_only(built)
    seen = sorted({text for page in built.pages.values() for text in visible_texts(page.markup)
                   if any(char.isalpha() for char in text)})
    indexed = {text["t.content"] for text in built.reader.list_texts()}
    missing = [text for text in seen if not any(text in content for content in indexed)]
    assert not missing, f"{len(missing)} of {len(seen)} texts not indexed, e.g. {missing[:5]}"
    step = max(len(seen) // _SEARCHED_TEXTS, 1)
    not_found = [text for text in seen[::step]
                 if not built.tools.dispatch("search", {"query": text}, "prototype").startswith("# Resultados")]
    assert not not_found, not_found


def test_every_screen_assembles_whole(built):
    cut = []
    for screen in (s["name"] for s in built.reader.list_screens()):
        part, answer = 1, ""
        while "## 8. Completude" not in answer:
            answer = built.tools.dispatch("assemble_page", {"name": screen, "part": part}, "prototype")
            assert part < 50 and not answer.startswith("Parte inválida"), f"{screen}: never reaches its end"
            part += 1
        if "nada foi cortado" not in answer:
            cut.append(screen)
    assert not cut, cut


def test_the_lists_a_page_writes_reach_its_assembly(built):
    _canvas_only(built)
    missing = {}
    for name, page in built.pages.items():
        written = set(literal_lists(page.logic)) & set(_RE_LOOP.findall(page.markup))
        assembly = built.reader.get_screen_assembly(name)
        given = {entry["key"].split(" · ")[0] for entry in assembly["data"]}
        if written - given:
            missing[name] = sorted(written - given)
    assert not missing, missing


def test_a_react_prototype_functions_come_back_verbatim(built):
    if built.capture == "dc_canvas":
        pytest.skip("a DC canvas is checked by rebuilding its screens")
    result = round_trip(built.document, built.capture, built.reader)
    assert result["checked"] and result["verbatim"] == result["checked"], result
