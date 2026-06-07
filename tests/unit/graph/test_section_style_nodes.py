"""
TDD — Etapa 2: Section container styles as proper graph nodes.

Before: Section.styles_json was an opaque JSON string blob.
After:  Section styles are written as Style nodes linked via SECTION_HAS_STYLE,
        enabling graph traversal and typed queries.

The styles_json field is retained for backward compatibility but the canonical
source of truth is now the SECTION_HAS_STYLE → Style relationship.
"""

from __future__ import annotations

import kuzu
import pytest

from design_graph.core.models import (
    DesignToken,
    ExtractedComponent,
    ExtractedScreen,
    ExtractedSection,
    StyleEntry,
)
from design_graph.graph.reader import GraphReader
from design_graph.graph.schema import initialize_schema
from design_graph.graph.writer import GraphWriter


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def section_graph(tmp_path_factory):
    """
    Graph with a screen that has a section with container styles.
    Section 'Header' has styles: padding=24px, backgroundColor=#1a1a1a.
    Section 'Footer' has no styles.
    """
    tmp  = tmp_path_factory.mktemp("section_style")
    db   = kuzu.Database(str(tmp / "sec.db"))
    conn = kuzu.Connection(db)
    initialize_schema(conn)
    gw = GraphWriter(conn)

    gw.write_tokens([])
    comp = ExtractedComponent(
        name="NavItem", comp_type="component", jsx_snippet="<a/>",
        occurrence=1, classes="", styles=[], interactions=[], texts=[], child_refs=[],
    )
    gw.write_component(comp, {})

    screen = ExtractedScreen(name="LandingPage", component_refs=["NavItem"], sections_count=0)
    header = ExtractedSection(
        id="sec_header", screen="LandingPage", name="Header",
        styles={"padding": "24px", "backgroundColor": "#1a1a1a", "display": "flex"},
        component_refs=["NavItem"],
        texts=["Welcome"],
        jsx_snippet="<header/>",
        detection_method="semantic",
    )
    footer = ExtractedSection(
        id="sec_footer", screen="LandingPage", name="Footer",
        styles={},
        component_refs=[],
        texts=[],
        jsx_snippet="<footer/>",
        detection_method="semantic",
    )
    gw.write_screen(screen, [header, footer], {})

    return conn


class TestSectionStyleNodesWritten:
    def test_section_has_style_relationship_exists_in_schema(self):
        """SECTION_HAS_STYLE rel must be defined — verify via schema DDL list."""
        from design_graph.graph.schema import SCHEMA
        ddl = " ".join(SCHEMA)
        assert "SECTION_HAS_STYLE" in ddl

    def test_section_style_nodes_created_for_each_property(self, section_graph):
        """One Style node per style property in the section's styles dict."""
        result = section_graph.execute(
            "MATCH (sec:Section {id:'sec_header'})-[:SECTION_HAS_STYLE]->(s:Style) "
            "RETURN s.property, s.value ORDER BY s.property"
        )
        rows = []
        while result.has_next():
            rows.append(result.get_next())
        props = {r[0]: r[1] for r in rows}
        assert props.get("padding") == "24px"
        assert props.get("backgroundColor") == "#1a1a1a"
        assert props.get("display") == "flex"

    def test_section_with_no_styles_has_no_style_nodes(self, section_graph):
        result = section_graph.execute(
            "MATCH (sec:Section {id:'sec_footer'})-[:SECTION_HAS_STYLE]->(s:Style) "
            "RETURN count(s) AS cnt"
        )
        cnt = result.get_next()[0] if result.has_next() else 0
        assert cnt == 0

    def test_section_style_nodes_have_section_element_and_default_state(self, section_graph):
        result = section_graph.execute(
            "MATCH (sec:Section {id:'sec_header'})-[:SECTION_HAS_STYLE]->(s:Style) "
            "RETURN s.element, s.state LIMIT 1"
        )
        row = result.get_next() if result.has_next() else None
        assert row is not None
        assert row[0] == "sec_header"   # element = section id
        assert row[1] == "default"


class TestReaderGetSectionStyles:
    def test_get_section_styles_returns_property_value_pairs(self, section_graph):
        reader = GraphReader(section_graph)
        styles = reader.get_section_styles("sec_header")
        props = {s["property"]: s["value"] for s in styles}
        assert props["padding"] == "24px"
        assert props["backgroundColor"] == "#1a1a1a"
        assert props["display"] == "flex"

    def test_get_section_styles_returns_empty_for_section_with_no_styles(self, section_graph):
        reader = GraphReader(section_graph)
        assert reader.get_section_styles("sec_footer") == []

    def test_get_section_styles_returns_empty_for_unknown_section(self, section_graph):
        reader = GraphReader(section_graph)
        assert reader.get_section_styles("nonexistent_id") == []

    def test_get_section_includes_structured_styles(self, section_graph):
        """get_section() must include styles from the graph, not only from JSON blob."""
        reader = GraphReader(section_graph)
        section = reader.get_section("LandingPage", "Header")
        assert section is not None
        styles = section.get("styles", {})
        assert styles.get("padding") == "24px"
