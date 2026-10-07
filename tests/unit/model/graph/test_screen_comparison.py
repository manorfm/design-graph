"""What a screen holds, to tell two variants apart: the components it renders, its texts and its style declarations."""

import kuzu
import pytest

from design_graph.model.entities import DetectionMethod, ExtractedComponent, ExtractedScreen, ExtractedSection, StyleEntry
from design_graph.model.graph.reader import GraphReader
from design_graph.model.graph.schema import initialize_schema
from design_graph.model.graph.writer import GraphWriter


def _comp(name, child_refs=()):
    return ExtractedComponent(name=name, comp_type="component", source_code=f"<{name}/>", occurrence=1, classes="",
                              child_refs=list(child_refs), source_lang="html")


def _section(screen, texts, styles):
    return ExtractedSection.create(screen=screen, name="Topo", styles={}, component_refs=[], texts=texts,
                                   source_code="<div/>", detection_method=DetectionMethod.STRUCTURAL,
                                   element_styles=styles)


@pytest.fixture()
def reader(tmp_path):
    conn = kuzu.Connection(kuzu.Database(str(tmp_path / "compare.db")))
    initialize_schema(conn)
    w = GraphWriter(conn)
    for comp in (_comp("Cell"), _comp("Grid", ["Cell"]), _comp("Sidebar")):
        w.write_component(comp)
    w.write_screen(ExtractedScreen(name="Home", component_refs=["Grid"],
                                   styles=[StyleEntry.create("div", "width", "390px")]),
                   [_section("Home", ["Olá", "Só no celular"], [StyleEntry.create("p", "gap", "8px")])])
    w.write_screen(ExtractedScreen(name="Home (desktop)", component_refs=["Grid", "Sidebar"]),
                   [_section("Home (desktop)", ["Olá"], [StyleEntry.create("p", "gap", "24px")])])
    w.commit()
    return GraphReader(conn)


def test_components_are_every_one_the_screen_renders_nested_included(reader):
    assert reader.screen_contents("Home")["components"] == ["Cell", "Grid"]


def test_texts_and_style_declarations_come_from_the_screen_and_its_sections(reader):
    contents = reader.screen_contents("Home")
    assert contents["texts"] == ["Olá", "Só no celular"]
    assert contents["styles"] == ["gap: 8px", "width: 390px"]


def test_the_name_is_resolved_and_an_unknown_screen_is_none(reader):
    assert reader.screen_contents("home (desktop)")["name"] == "Home (desktop)"
    assert reader.screen_contents("Inexistente") is None
