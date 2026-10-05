"""
Screens relate to each other beyond composition: a screen navigates to
others (a link, a "Next" button) and may be a variant of another screen —
the same page at another viewport or in another mode. The viewport a screen
was designed for travels with it.
"""

from __future__ import annotations

from types import SimpleNamespace

import kuzu
import pytest

from tests.support.graph import writer_and_reader
from design_graph.model.entities import ExtractedScreen, ScreenLink
from design_graph.model.graph.reader import GraphReader
from design_graph.model.graph.schema import initialize_schema
from design_graph.model.graph.writer import GraphWriter


@pytest.fixture()
def graph(tmp_path):
    db = kuzu.Database(str(tmp_path / "relations.db"))
    conn = kuzu.Connection(db)
    initialize_schema(conn)
    return writer_and_reader(conn)


def _write(graph, *screens: ExtractedScreen) -> None:
    graph.writer.declare_screens(list(screens))
    for screen in screens:
        graph.writer.write_screen(screen, [])


class TestScreenLink:
    def test_target_is_required(self):
        with pytest.raises(ValueError):
            ScreenLink(target="  ")

    def test_label_defaults_to_empty(self):
        assert ScreenLink(target="Contexto").label == ""


class TestViewport:
    def test_viewport_survives_write_and_read(self, graph):
        _write(graph, ExtractedScreen(name="Welcome", viewport_width=390, viewport_height=844))
        assert graph.reader.get_screen_relations("Welcome")["viewport"] == {"width": 390, "height": 844}

    def test_unknown_viewport_reads_as_none(self, graph):
        _write(graph, ExtractedScreen(name="Welcome"))
        assert graph.reader.get_screen_relations("Welcome")["viewport"] is None


class TestNavigation:
    def test_links_become_navigation_both_ways(self, graph):
        _write(
            graph,
            ExtractedScreen(name="Welcome", links=[ScreenLink("Perspective", "Start")]),
            ExtractedScreen(name="Perspective", links=[ScreenLink("Welcome", "Back")]),
        )
        welcome = graph.reader.get_screen_relations("Welcome")
        assert welcome["navigates_to"] == [{"screen": "Perspective", "label": "Start"}]
        assert welcome["navigated_from"] == [{"screen": "Perspective", "label": "Back"}]

    def test_link_to_an_unknown_screen_is_dropped(self, graph):
        _write(graph, ExtractedScreen(name="Welcome", links=[ScreenLink("Nowhere", "Go")]))
        assert graph.reader.get_screen_relations("Welcome")["navigates_to"] == []

    def test_repeated_link_is_written_once(self, graph):
        _write(
            graph,
            ExtractedScreen(name="Map", links=[ScreenLink("Report", "Report"), ScreenLink("Report", "Report")]),
            ExtractedScreen(name="Report"),
        )
        assert graph.reader.get_screen_relations("Map")["navigates_to"] == [{"screen": "Report", "label": "Report"}]


class TestVariants:
    def test_variant_points_at_its_base_screen_and_back(self, graph):
        _write(
            graph,
            ExtractedScreen(name="Report"),
            ExtractedScreen(name="Report (dark)", variant_of="Report", variant_axis="mode"),
        )
        assert graph.reader.get_screen_relations("Report (dark)")["variant_of"] == {"screen": "Report", "axis": "mode"}
        assert graph.reader.get_screen_relations("Report")["variants"] == [{"screen": "Report (dark)", "axis": "mode"}]

    def test_list_screens_names_each_variant_base(self, graph):
        _write(
            graph,
            ExtractedScreen(name="Report"),
            ExtractedScreen(name="Report (dark)", variant_of="Report", variant_axis="mode"),
        )
        by_name = {s["name"]: s for s in graph.reader.list_screens()}
        assert by_name["Report (dark)"]["variant_of"] == "Report"
        assert by_name["Report"]["variant_of"] == ""

    def test_screen_full_and_screen_carry_relations(self, graph):
        _write(graph, ExtractedScreen(name="Welcome", viewport_width=390, viewport_height=844))
        assert graph.reader.get_screen("Welcome")["relations"]["viewport"]["width"] == 390
        assert graph.reader.get_screen_full("Welcome")["relations"]["viewport"]["height"] == 844

    def test_relations_of_unknown_screen_are_none(self, graph):
        assert graph.reader.get_screen_relations("Nothing") is None
