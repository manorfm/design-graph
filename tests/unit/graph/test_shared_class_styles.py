"""
Tests for GraphReader.find_styles_by_class — C36 P3.

A CSS class reused across several screens/components but never factored
into a named React component (e.g. `.page-title`, `.chip`, `.audit-dot`)
was completely invisible to search()/get_component_spec(): neither queries
by Style.element, only by Component node name. Once a shared class's
styles are attributed correctly (C36 P1), the graph already models "one
class = one reusable set of facts" — find_styles_by_class is the missing
read path to reach it directly, without needing to know which component or
section happens to reference it.
"""

from __future__ import annotations

import kuzu
import pytest

from design_graph.core.models import (
    ExtractedComponent,
    ExtractedScreen,
    ExtractedSection,
    StyleEntry,
)
from design_graph.graph.reader import GraphReader
from design_graph.graph.schema import initialize_schema
from design_graph.graph.writer import GraphWriter


@pytest.fixture(scope="module")
def shared_class_graph(tmp_path_factory):
    """
    `.chip` is resolved by two different owners on two different screens:
    - PageTitle (a named Component) uses .chip
    - the "Row" Section on HistoryView also uses .chip (inline list markup,
      no named component)
    `.lonely` is used by exactly one component — still findable, just with
    one owner reported.
    """
    tmp  = tmp_path_factory.mktemp("shared_class")
    db   = kuzu.Database(str(tmp / "shared.db"))
    conn = kuzu.Connection(db)
    initialize_schema(conn)
    gw = GraphWriter(conn)
    gw.write_tokens([])

    chip_style = StyleEntry.from_css_class("chip", "border-radius", "999px")
    lonely_style = StyleEntry.from_css_class("lonely", "color", "red")

    page_title = ExtractedComponent(
        name="PageTitle", comp_type="component", jsx_snippet='<div className="chip"/>',
        occurrence=1, classes="chip", styles=[chip_style, lonely_style],
        interactions=[], texts=[], child_refs=[],
    )
    gw.write_component(page_title, {})

    history_screen = ExtractedScreen(name="HistoryView", component_refs=[], sections_count=0)
    row_section = ExtractedSection(
        id="sec_row", screen="HistoryView", name="Row",
        styles={}, component_refs=[], texts=[], jsx_snippet="",
        detection_method="list_item", element_styles=[chip_style],
    )
    gw.write_screen(history_screen, [row_section], {})

    return GraphReader(conn)


class TestFindStylesByClass:
    def test_returns_properties_for_a_shared_class(self, shared_class_graph):
        rows = shared_class_graph.find_styles_by_class("chip")
        props = {(r["property"], r["value"]) for r in rows}
        assert ("border-radius", "999px") in props

    def test_unknown_class_returns_empty(self, shared_class_graph):
        assert shared_class_graph.find_styles_by_class("does-not-exist") == []

    def test_reports_component_owner(self, shared_class_graph):
        owners = shared_class_graph.find_class_owners("chip")
        assert "PageTitle" in owners["components"]

    def test_reports_section_owner_with_its_screen(self, shared_class_graph):
        owners = shared_class_graph.find_class_owners("chip")
        assert {"screen": "HistoryView", "section": "Row"} in owners["sections"]

    def test_single_owner_class_still_resolves(self, shared_class_graph):
        rows = shared_class_graph.find_styles_by_class("lonely")
        assert {"property": "color", "value": "red"} in [
            {"property": r["property"], "value": r["value"]} for r in rows
        ]
        owners = shared_class_graph.find_class_owners("lonely")
        assert owners["components"] == ["PageTitle"]
        assert owners["sections"] == []
