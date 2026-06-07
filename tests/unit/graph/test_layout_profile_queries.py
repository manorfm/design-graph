"""
TDD — Etapa 1: LayoutProfile queries on GraphReader.

Tests for get_component_layout_profile() and get_screen_layout().
These methods filter existing Style nodes for layout-relevant CSS properties
without any schema change.
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
from design_graph.graph.reader import GraphReader, _build_layout_profile
from design_graph.graph.schema import initialize_schema
from design_graph.graph.writer import GraphWriter
from design_graph.parsing.token_extractor import build_token_map


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def layout_graph(tmp_path_factory):
    """
    Graph with 2 components on 1 screen:
    - FlexCard:  display=flex, flexDirection=column, width=100%, padding=16px,
                 backgroundColor=#111 (visual — must be filtered out)
    - GridList:  display=grid, gap=8px, overflow=hidden
    - BareComp:  no styles at all
    Screen: DashboardPage uses all three.
    """
    tmp  = tmp_path_factory.mktemp("layout")
    db   = kuzu.Database(str(tmp / "layout.db"))
    conn = kuzu.Connection(db)
    initialize_schema(conn)
    gw = GraphWriter(conn)

    gw.write_tokens([])

    flex_card = ExtractedComponent(
        name="FlexCard", comp_type="card", jsx_snippet="<div/>",
        occurrence=2, classes="",
        styles=[
            StyleEntry(id="s1", element="FlexCard", state="default", property="display",       value="flex"),
            StyleEntry(id="s2", element="FlexCard", state="default", property="flexDirection",  value="column"),
            StyleEntry(id="s3", element="FlexCard", state="default", property="width",          value="100%"),
            StyleEntry(id="s4", element="FlexCard", state="default", property="padding",        value="16px"),
            StyleEntry(id="s5", element="FlexCard", state="default", property="backgroundColor",value="#111"),
            StyleEntry(id="s6", element="FlexCard", state="hover",   property="display",        value="block"),
        ],
    )
    grid_list = ExtractedComponent(
        name="GridList", comp_type="list-item", jsx_snippet="<ul/>",
        occurrence=1, classes="",
        styles=[
            StyleEntry(id="s7", element="GridList", state="default", property="display",  value="grid"),
            StyleEntry(id="s8", element="GridList", state="default", property="gap",      value="8px"),
            StyleEntry(id="s9", element="GridList", state="default", property="overflow", value="hidden"),
        ],
    )
    bare_comp = ExtractedComponent(
        name="BareComp", comp_type="component", jsx_snippet="<span/>",
        occurrence=1, classes="",
        styles=[],
    )

    gw.write_component(flex_card, {})
    gw.write_component(grid_list, {})
    gw.write_component(bare_comp, {})

    screen = ExtractedScreen(
        name="DashboardPage",
        component_refs=["FlexCard", "GridList", "BareComp"],
        sections_count=0,
    )
    section = ExtractedSection(
        id="sec1", screen="DashboardPage", name="Main",
        styles={}, component_refs=["FlexCard"], texts=[], jsx_snippet="",
        detection_method="semantic",
    )
    gw.write_screen(screen, [section], {})

    return GraphReader(conn)


# ── get_component_layout_profile ─────────────────────────────────────────────

class TestGetComponentLayoutProfile:
    def test_returns_none_for_unknown_component(self, layout_graph):
        assert layout_graph.get_component_layout_profile("DoesNotExist") is None

    def test_extracts_layout_properties_from_default_state(self, layout_graph):
        profile = layout_graph.get_component_layout_profile("FlexCard")
        assert profile is not None
        assert profile["display"] == "flex"
        assert profile["flex_direction"] == "column"
        assert profile["width"] == "100%"
        assert profile["padding"] == "16px"

    def test_ignores_visual_properties(self, layout_graph):
        profile = layout_graph.get_component_layout_profile("FlexCard")
        assert "backgroundColor" not in profile
        assert "extra_layout" in profile
        assert "backgroundColor" not in profile["extra_layout"]

    def test_ignores_non_default_state_styles(self, layout_graph):
        """hover/focus styles must not appear in the layout profile (default only)."""
        profile = layout_graph.get_component_layout_profile("FlexCard")
        # FlexCard has display=block in hover state — must not override default display=flex
        assert profile["display"] == "flex"

    def test_grid_component_profile(self, layout_graph):
        profile = layout_graph.get_component_layout_profile("GridList")
        assert profile["display"] == "grid"
        assert profile["gap"] == "8px"
        assert profile["overflow"] == "hidden"

    def test_component_with_no_styles_returns_profile_with_none_fields(self, layout_graph):
        profile = layout_graph.get_component_layout_profile("BareComp")
        assert profile is not None
        assert profile["display"] is None
        assert profile["width"] is None
        assert profile["extra_layout"] == {}

    def test_component_name_is_included_in_profile(self, layout_graph):
        profile = layout_graph.get_component_layout_profile("FlexCard")
        assert profile["component_name"] == "FlexCard"

    def test_fuzzy_resolution_works(self, layout_graph):
        profile = layout_graph.get_component_layout_profile("Flex")  # partial name
        assert profile is not None
        assert profile["component_name"] == "FlexCard"


# ── get_screen_layout ─────────────────────────────────────────────────────────

class TestGetScreenLayout:
    def test_returns_empty_for_unknown_screen(self, layout_graph):
        assert layout_graph.get_screen_layout("NoSuchScreen") == []

    def test_returns_one_entry_per_screen_component(self, layout_graph):
        profiles = layout_graph.get_screen_layout("DashboardPage")
        names = {p["component_name"] for p in profiles}
        assert "FlexCard" in names
        assert "GridList" in names
        assert "BareComp" in names

    def test_layout_values_are_correct_in_screen_result(self, layout_graph):
        profiles = layout_graph.get_screen_layout("DashboardPage")
        flex = next(p for p in profiles if p["component_name"] == "FlexCard")
        assert flex["display"] == "flex"
        assert flex["flex_direction"] == "column"

    def test_uses_single_join_query_not_n_plus_one(self, layout_graph, monkeypatch):
        """get_screen_layout must call _q at most 2 times (one for comps, one for styles)."""
        call_count = 0
        original_q = layout_graph._q

        def counting_q(cypher, params=None):
            nonlocal call_count
            call_count += 1
            return original_q(cypher, params)

        monkeypatch.setattr(layout_graph, "_q", counting_q)
        layout_graph.get_screen_layout("DashboardPage")
        assert call_count <= 3  # screen fuzzy + comp query + style join (not N per component)

    def test_fuzzy_screen_resolution_works(self, layout_graph):
        profiles = layout_graph.get_screen_layout("Dashboard")  # partial name
        assert len(profiles) > 0


# ── _build_layout_profile helper ─────────────────────────────────────────────

class TestBuildLayoutProfileHelper:
    def test_maps_camel_case_to_snake_case_keys(self):
        props = {"flexDirection": "row", "alignItems": "center", "justifyContent": "space-between"}
        profile = _build_layout_profile("MyComp", props)
        assert profile["flex_direction"] == "row"
        assert profile["align_items"] == "center"
        assert profile["justify_content"] == "space-between"

    def test_unknown_layout_props_go_into_extra_layout(self):
        props = {"display": "flex", "minWidth": "200px", "boxSizing": "border-box"}
        profile = _build_layout_profile("MyComp", props)
        assert profile["display"] == "flex"
        assert profile["extra_layout"]["minWidth"] == "200px"
        assert profile["extra_layout"]["boxSizing"] == "border-box"

    def test_empty_props_produces_all_none_profile(self):
        profile = _build_layout_profile("MyComp", {})
        assert profile["display"] is None
        assert profile["extra_layout"] == {}

    def test_padding_shorthand_and_individual_sides(self):
        props = {"paddingTop": "8px", "paddingBottom": "16px"}
        profile = _build_layout_profile("MyComp", props)
        assert profile["padding_top"] == "8px"
        assert profile["padding_bottom"] == "16px"
        assert profile["padding"] is None
