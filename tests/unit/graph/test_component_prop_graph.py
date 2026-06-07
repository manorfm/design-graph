"""
TDD — Etapa 5b: ComponentProp schema, writer, and reader.

Tests that ComponentProp nodes and HAS_PROP relationships are correctly
written to and queried from the graph.
"""

from __future__ import annotations

import kuzu
import pytest

from design_graph.core.models import (
    ComponentProp,
    ExtractedComponent,
    ExtractedScreen,
)
from design_graph.graph.reader import GraphReader
from design_graph.graph.schema import initialize_schema
from design_graph.graph.writer import GraphWriter


@pytest.fixture(scope="module")
def prop_graph(tmp_path_factory):
    """
    Graph with:
    - NavBar: props title (required), sticky=false (optional)
    - BtnPrimary: props label (required), variant='primary' (optional)
    - Screen DashboardPage using both
    """
    tmp  = tmp_path_factory.mktemp("prop")
    db   = kuzu.Database(str(tmp / "p.db"))
    conn = kuzu.Connection(db)
    initialize_schema(conn)
    gw = GraphWriter(conn)

    gw.write_tokens([])
    navbar = ExtractedComponent(
        name="NavBar", comp_type="navigation", jsx_snippet="<nav/>",
        occurrence=1, classes="",
        props=[
            ComponentProp(id="p1", component_name="NavBar", prop_name="title",  default_value=""),
            ComponentProp(id="p2", component_name="NavBar", prop_name="sticky", default_value="false"),
        ],
    )
    btn = ExtractedComponent(
        name="BtnPrimary", comp_type="button", jsx_snippet="<button/>",
        occurrence=3, classes="",
        props=[
            ComponentProp(id="p3", component_name="BtnPrimary", prop_name="label",   default_value=""),
            ComponentProp(id="p4", component_name="BtnPrimary", prop_name="variant", default_value="primary"),
        ],
    )
    gw.write_component(navbar, {})
    gw.write_component(btn, {})

    screen = ExtractedScreen(name="DashboardPage", component_refs=["NavBar", "BtnPrimary"])
    gw.write_screen(screen, [], {})

    return conn


class TestComponentPropSchema:
    def test_component_prop_node_table_in_ddl(self):
        from design_graph.graph.schema import SCHEMA
        ddl = " ".join(SCHEMA)
        assert "ComponentProp" in ddl

    def test_has_prop_relationship_in_ddl(self):
        from design_graph.graph.schema import SCHEMA
        ddl = " ".join(SCHEMA)
        assert "HAS_PROP" in ddl


class TestComponentPropWriter:
    def test_prop_nodes_created_for_each_declared_prop(self, prop_graph):
        result = prop_graph.execute(
            "MATCH (c:Component {name:'NavBar'})-[:HAS_PROP]->(p:ComponentProp) "
            "RETURN p.prop_name ORDER BY p.prop_name"
        )
        names = []
        while result.has_next():
            names.append(result.get_next()[0])
        assert set(names) == {"title", "sticky"}

    def test_required_prop_has_empty_default_value(self, prop_graph):
        result = prop_graph.execute(
            "MATCH (c:Component {name:'NavBar'})-[:HAS_PROP]->"
            "(p:ComponentProp {prop_name:'title'}) RETURN p.default_value"
        )
        row = result.get_next() if result.has_next() else None
        assert row is not None
        assert row[0] == ""

    def test_optional_prop_has_correct_default_value(self, prop_graph):
        result = prop_graph.execute(
            "MATCH (c:Component {name:'BtnPrimary'})-[:HAS_PROP]->"
            "(p:ComponentProp {prop_name:'variant'}) RETURN p.default_value"
        )
        row = result.get_next() if result.has_next() else None
        assert row is not None
        assert row[0] == "primary"

    def test_component_without_props_has_no_prop_nodes(self, prop_graph):
        """Components with no declared props must have no HAS_PROP edges."""
        # Add a bare component with no props
        gw = GraphWriter(prop_graph)
        bare = ExtractedComponent(
            name="BareIcon", comp_type="component", jsx_snippet="<svg/>",
            occurrence=1, classes="", props=[],
        )
        gw.write_component(bare, {})
        result = prop_graph.execute(
            "MATCH (c:Component {name:'BareIcon'})-[:HAS_PROP]->(p:ComponentProp) "
            "RETURN count(p) AS cnt"
        )
        cnt = result.get_next()[0] if result.has_next() else 0
        assert cnt == 0

    def test_duplicate_prop_write_is_idempotent(self, prop_graph):
        """Writing the same component twice must not duplicate prop nodes."""
        gw = GraphWriter(prop_graph)
        navbar = ExtractedComponent(
            name="NavBar", comp_type="navigation", jsx_snippet="<nav/>",
            occurrence=1, classes="",
            props=[ComponentProp(id="p1", component_name="NavBar", prop_name="title", default_value="")],
        )
        gw.write_component(navbar, {})  # second write
        result = prop_graph.execute(
            "MATCH (c:Component {name:'NavBar'})-[:HAS_PROP]->"
            "(p:ComponentProp {prop_name:'title'}) RETURN count(p)"
        )
        cnt = result.get_next()[0] if result.has_next() else 0
        assert cnt == 1


class TestComponentPropReader:
    def test_get_component_props_returns_all_props(self, prop_graph):
        reader = GraphReader(prop_graph)
        props = reader.get_component_props("NavBar")
        names = {p["prop_name"] for p in props}
        assert names == {"title", "sticky"}

    def test_get_component_props_includes_default_value(self, prop_graph):
        reader = GraphReader(prop_graph)
        props = reader.get_component_props("BtnPrimary")
        variant = next(p for p in props if p["prop_name"] == "variant")
        assert variant["default_value"] == "primary"

    def test_get_component_props_returns_empty_for_unknown(self, prop_graph):
        reader = GraphReader(prop_graph)
        assert reader.get_component_props("DoesNotExist") == []

    def test_get_component_props_fuzzy_name_resolution(self, prop_graph):
        reader = GraphReader(prop_graph)
        props = reader.get_component_props("Nav")  # partial
        assert len(props) > 0

    def test_get_component_spec_includes_props(self, prop_graph):
        reader = GraphReader(prop_graph)
        spec = reader.get_component_spec("NavBar")
        assert spec is not None
        assert "props" in spec
        prop_names = {p["prop_name"] for p in spec["props"]}
        assert "title" in prop_names
