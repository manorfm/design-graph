"""
TDD — Etapa 4: Section texts as UIText graph nodes.

Before: Section.texts_json was a JSON list-of-strings blob.
After:  Section texts are written as UIText nodes linked via SECTION_HAS_TEXT,
        enabling typed queries and consistency with component UIText nodes.

Also covers the fix for get_screen() which previously returned texts=[] always.
"""

from __future__ import annotations

import kuzu
import pytest

from design_graph.core.models import (
    ExtractedComponent,
    ExtractedScreen,
    ExtractedSection,
    TextEntry,
)
from design_graph.graph.reader import GraphReader
from design_graph.graph.schema import initialize_schema
from design_graph.graph.writer import GraphWriter


# ── Shared fixture ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def text_graph(tmp_path_factory):
    """
    Graph with:
    - HeaderSection: texts=['Welcome back', 'Get started']
    - FooterSection: no texts
    - Component BtnPrimary with UIText 'Confirm'
    - Screen LandingPage using BtnPrimary, sections Header + Footer
    """
    tmp  = tmp_path_factory.mktemp("sec_text")
    db   = kuzu.Database(str(tmp / "t.db"))
    conn = kuzu.Connection(db)
    initialize_schema(conn)
    gw = GraphWriter(conn)

    gw.write_tokens([])
    btn = ExtractedComponent(
        name="BtnPrimary", comp_type="button", jsx_snippet="<button>Confirm</button>",
        occurrence=2, classes="",
        texts=[TextEntry(id="txt1", content="Confirm", text_type="button",
                         source="BtnPrimary", element="button")],
    )
    gw.write_component(btn, {})

    screen = ExtractedScreen(
        name="LandingPage", component_refs=["BtnPrimary"], sections_count=0
    )
    header = ExtractedSection(
        id="sec_hdr", screen="LandingPage", name="Header",
        styles={"padding": "24px"},
        component_refs=["BtnPrimary"],
        texts=["Welcome back", "Get started"],
        jsx_snippet="<header/>",
        detection_method="semantic",
    )
    footer = ExtractedSection(
        id="sec_ftr", screen="LandingPage", name="Footer",
        styles={},
        component_refs=[],
        texts=[],
        jsx_snippet="<footer/>",
        detection_method="semantic",
    )
    gw.write_screen(screen, [header, footer], {})

    return conn


# ── Schema ────────────────────────────────────────────────────────────────────

class TestSectionTextSchema:
    def test_section_has_text_relationship_in_schema_ddl(self):
        from design_graph.graph.schema import SCHEMA
        ddl = " ".join(SCHEMA)
        assert "SECTION_HAS_TEXT" in ddl


# ── Writer ────────────────────────────────────────────────────────────────────

class TestSectionTextNodesWritten:
    def test_uitext_nodes_created_for_section_texts(self, text_graph):
        result = text_graph.execute(
            "MATCH (sec:Section {id:'sec_hdr'})-[:SECTION_HAS_TEXT]->(t:UIText) "
            "RETURN t.content ORDER BY t.content"
        )
        contents = []
        while result.has_next():
            contents.append(result.get_next()[0])
        assert set(contents) == {"Welcome back", "Get started"}

    def test_uitext_nodes_have_correct_source_and_type(self, text_graph):
        result = text_graph.execute(
            "MATCH (sec:Section {id:'sec_hdr'})-[:SECTION_HAS_TEXT]->(t:UIText) "
            "RETURN t.source, t.text_type LIMIT 1"
        )
        row = result.get_next() if result.has_next() else None
        assert row is not None
        assert row[0] == "sec_hdr"           # source = section id
        assert row[1] == "section_text"       # text_type identifies origin

    def test_footer_section_with_no_texts_has_no_uitext_nodes(self, text_graph):
        result = text_graph.execute(
            "MATCH (sec:Section {id:'sec_ftr'})-[:SECTION_HAS_TEXT]->(t:UIText) "
            "RETURN count(t) AS cnt"
        )
        cnt = result.get_next()[0] if result.has_next() else 0
        assert cnt == 0


# ── Reader: get_section_texts ──────────────────────────────────────────────────

class TestReaderGetSectionTexts:
    def test_returns_list_of_content_dicts(self, text_graph):
        reader = GraphReader(text_graph)
        texts = reader.get_section_texts("sec_hdr")
        contents = {t["content"] for t in texts}
        assert contents == {"Welcome back", "Get started"}

    def test_returns_empty_for_section_with_no_texts(self, text_graph):
        reader = GraphReader(text_graph)
        assert reader.get_section_texts("sec_ftr") == []

    def test_returns_empty_for_unknown_section_id(self, text_graph):
        reader = GraphReader(text_graph)
        assert reader.get_section_texts("nonexistent") == []


# ── Reader: get_section uses graph texts ──────────────────────────────────────

class TestGetSectionUsesGraphTexts:
    def test_get_section_texts_populated_from_graph_not_blob(self, text_graph):
        reader = GraphReader(text_graph)
        section = reader.get_section("LandingPage", "Header")
        assert section is not None
        texts = section.get("texts", [])
        assert "Welcome back" in texts
        assert "Get started" in texts

    def test_get_section_footer_texts_empty(self, text_graph):
        reader = GraphReader(text_graph)
        section = reader.get_section("LandingPage", "Footer")
        assert section is not None
        assert section.get("texts", []) == []


# ── Reader: get_screen populates texts ───────────────────────────────────────

class TestGetScreenTextsPopulated:
    def test_get_screen_texts_not_hardcoded_empty(self, text_graph):
        reader = GraphReader(text_graph)
        screen = reader.get_screen("LandingPage")
        assert screen is not None
        texts = screen.get("texts", [])
        assert isinstance(texts, list)
        assert len(texts) > 0, "get_screen should return component UITexts, not hardcoded []"

    def test_get_screen_texts_include_component_uitext_content(self, text_graph):
        reader = GraphReader(text_graph)
        screen = reader.get_screen("LandingPage")
        contents = [t.get("content") or t.get("t.content") for t in screen["texts"]]
        assert "Confirm" in contents
