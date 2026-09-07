"""
Round-trip test for Component.referenced_data_json (docs/changes/C39) —
data a component's own body references by name from a module-level
constant (e.g. an icon-name -> SVG-path lookup table), written by
GraphWriter and read back by GraphReader through get_component,
get_component_spec and get_component_full.
"""

from __future__ import annotations

import kuzu
import pytest

from design_graph.core.models import ExtractedComponent, ExtractedScreen
from design_graph.graph.reader import GraphReader
from design_graph.graph.schema import initialize_schema
from design_graph.graph.writer import GraphWriter

ICONS_DATA = {"lock": "M21 2l-2 2", "trash": "M3 6h18"}


@pytest.fixture(scope="module")
def icon_graph(tmp_path_factory):
    tmp  = tmp_path_factory.mktemp("referenced_data")
    db   = kuzu.Database(str(tmp / "d.db"))
    conn = kuzu.Connection(db)
    initialize_schema(conn)
    gw = GraphWriter(conn)

    gw.write_tokens([])
    icon = ExtractedComponent(
        name="Icon", comp_type="component", jsx_snippet="<svg/>",
        occurrence=1, classes="",
        referenced_data={"ICONS": ICONS_DATA},
    )
    plain = ExtractedComponent(
        name="Btn", comp_type="button", jsx_snippet="<button/>",
        occurrence=2, classes="",
    )
    gw.write_component(icon, {})
    gw.write_component(plain, {})

    screen = ExtractedScreen(name="LoginScreen", component_refs=["Icon", "Btn"])
    gw.write_screen(screen, [], {})

    return conn


@pytest.fixture(scope="module")
def reader(icon_graph):
    return GraphReader(icon_graph)


class TestReferencedDataRoundTrip:
    def test_get_component_returns_referenced_data(self, reader):
        comp = reader.get_component("Icon")
        assert comp["referenced_data"] == {"ICONS": ICONS_DATA}

    def test_get_component_spec_returns_referenced_data(self, reader):
        spec = reader.get_component_spec("Icon")
        assert spec["referenced_data"] == {"ICONS": ICONS_DATA}

    def test_get_component_full_returns_referenced_data_on_root(self, reader):
        full = reader.get_component_full("Icon")
        root = next(c for c in full["components"] if c["name"] == "Icon")
        assert root["referenced_data"] == {"ICONS": ICONS_DATA}

    def test_component_without_referenced_data_gets_empty_dict(self, reader):
        comp = reader.get_component("Btn")
        assert comp["referenced_data"] == {}

    def test_get_screen_full_includes_referenced_data_per_component(self, reader):
        screen = reader.get_screen_full("LoginScreen")
        icon = next(c for c in screen["components"] if c["name"] == "Icon")
        assert icon["referenced_data"] == {"ICONS": ICONS_DATA}
