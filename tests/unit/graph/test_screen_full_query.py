"""
TDD — get_screen_full: composite screen query for AI-driven screen reconstruction.

Tests for GraphReader.get_screen_full(), which returns all data needed to
implement a screen in a single bounded-query call: sections (with styles and
texts), all components (with styles_by_state, tokens, texts, interactions,
props and children) and layout profiles.
"""

from __future__ import annotations

import kuzu
import pytest

from design_graph.core.models import (
    ComponentProp,
    ExtractedComponent,
    ExtractedScreen,
    ExtractedSection,
    InteractionEntry,
    StyleEntry,
    TextEntry,
)
from design_graph.graph.reader import GraphReader
from design_graph.graph.schema import initialize_schema
from design_graph.graph.writer import GraphWriter


# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def full_screen_graph(tmp_path_factory):
    """
    Graph with one screen, two sections, and three components:

    Screen:   HomeScreen
    Sections: HeroSection  (styles: padding=32px, texts: ["Welcome", "Get started"])
              ContentSection (no styles, no texts)

    Components:
      TopNav   — navigation, flex layout, hover interaction, two props (title required,
                 variant optional), one text "Home", child: Badge
      ContentCard — card, grid layout, child: Badge
      Badge    — leaf component, no props/styles/interactions
    """
    tmp  = tmp_path_factory.mktemp("full_screen")
    db   = kuzu.Database(str(tmp / "full.db"))
    conn = kuzu.Connection(db)
    initialize_schema(conn)
    gw   = GraphWriter(conn)
    gw.write_tokens([])

    badge = ExtractedComponent(
        name="Badge", comp_type="badge",
        jsx_snippet="<span>B</span>", occurrence=2, classes="",
        styles=[],
    )

    top_nav = ExtractedComponent(
        name="TopNav", comp_type="navigation",
        jsx_snippet="<nav>Home</nav>", occurrence=1, classes="nav-bar",
        styles=[
            StyleEntry(id="sn1", element="TopNav", state="default", property="display",         value="flex"),
            StyleEntry(id="sn2", element="TopNav", state="default", property="width",           value="100%"),
            StyleEntry(id="sn3", element="TopNav", state="hover",   property="backgroundColor", value="#f0f0f0"),
        ],
        interactions=[
            InteractionEntry(
                id="i1", trigger="hover", css_prop="backgroundColor",
                from_val="#fff", to_val="#f0f0f0", transition="all 0.2s",
            ),
        ],
        texts=[
            TextEntry(id="tx1", content="Home", text_type="heading", source="TopNav", element="h1"),
        ],
        props=[
            ComponentProp(id="pr1", component_name="TopNav", prop_name="title",   default_value=""),
            ComponentProp(id="pr2", component_name="TopNav", prop_name="variant", default_value="default"),
        ],
        child_refs=["Badge"],
    )

    content_card = ExtractedComponent(
        name="ContentCard", comp_type="card",
        jsx_snippet="<div>Content</div>", occurrence=1, classes="card",
        styles=[
            StyleEntry(id="sc1", element="ContentCard", state="default", property="display", value="grid"),
            StyleEntry(id="sc2", element="ContentCard", state="default", property="gap",     value="12px"),
        ],
        child_refs=["Badge"],
    )

    # Badge first so CONTAINS edges can be created immediately
    gw.write_component(badge, {})
    gw.write_component(top_nav, {})
    gw.write_component(content_card, {})
    gw.flush_pending_contains()

    hero = ExtractedSection(
        id="sec_hero", screen="HomeScreen", name="HeroSection",
        styles={"padding": "32px", "backgroundColor": "#000"},
        component_refs=["TopNav"],
        texts=["Welcome", "Get started"],
        jsx_snippet="<section>Hero</section>",
        detection_method="comment",
    )
    content = ExtractedSection(
        id="sec_content", screen="HomeScreen", name="ContentSection",
        styles={}, component_refs=["ContentCard"],
        texts=[], jsx_snippet="<section>Content</section>",
        detection_method="structural",
    )
    screen = ExtractedScreen(
        name="HomeScreen",
        component_refs=["TopNav", "ContentCard", "Badge"],
        sections_count=2,
    )
    gw.write_screen(screen, [hero, content], {})

    return GraphReader(conn)


# ── Not found ─────────────────────────────────────────────────────────────────

class TestGetScreenFullNotFound:
    def test_returns_none_for_unknown_screen(self, full_screen_graph):
        assert full_screen_graph.get_screen_full("NonExistentXYZ") is None


# ── Screen metadata ───────────────────────────────────────────────────────────

class TestGetScreenFullMetadata:
    def test_returns_screen_name(self, full_screen_graph):
        result = full_screen_graph.get_screen_full("HomeScreen")
        assert result is not None
        assert result["name"] == "HomeScreen"

    def test_returns_component_count(self, full_screen_graph):
        result = full_screen_graph.get_screen_full("HomeScreen")
        assert result["component_count"] >= 3

    def test_returns_sections_count(self, full_screen_graph):
        result = full_screen_graph.get_screen_full("HomeScreen")
        assert result["sections_count"] == 2

    def test_fuzzy_partial_name_resolves(self, full_screen_graph):
        result = full_screen_graph.get_screen_full("Home")
        assert result is not None
        assert result["name"] == "HomeScreen"


# ── Sections ──────────────────────────────────────────────────────────────────

class TestGetScreenFullSections:
    def test_includes_all_sections(self, full_screen_graph):
        result = full_screen_graph.get_screen_full("HomeScreen")
        names = {s["name"] for s in result["sections"]}
        assert "HeroSection"    in names
        assert "ContentSection" in names

    def test_section_includes_component_refs(self, full_screen_graph):
        result = full_screen_graph.get_screen_full("HomeScreen")
        hero   = next(s for s in result["sections"] if s["name"] == "HeroSection")
        assert "TopNav" in hero["component_refs"]

    def test_section_includes_styles(self, full_screen_graph):
        result = full_screen_graph.get_screen_full("HomeScreen")
        hero   = next(s for s in result["sections"] if s["name"] == "HeroSection")
        assert hero["styles"].get("padding") == "32px"

    def test_section_includes_texts(self, full_screen_graph):
        result = full_screen_graph.get_screen_full("HomeScreen")
        hero   = next(s for s in result["sections"] if s["name"] == "HeroSection")
        assert "Welcome" in hero["texts"]

    def test_section_includes_jsx_snippet(self, full_screen_graph):
        result = full_screen_graph.get_screen_full("HomeScreen")
        hero   = next(s for s in result["sections"] if s["name"] == "HeroSection")
        assert "Hero" in hero["jsx_snippet"]

    def test_section_includes_detection_method(self, full_screen_graph):
        result = full_screen_graph.get_screen_full("HomeScreen")
        hero   = next(s for s in result["sections"] if s["name"] == "HeroSection")
        assert hero["detection_method"] == "comment"


# ── Components ────────────────────────────────────────────────────────────────

class TestGetScreenFullComponents:
    def test_includes_all_screen_components(self, full_screen_graph):
        result = full_screen_graph.get_screen_full("HomeScreen")
        names  = {c["name"] for c in result["components"]}
        assert "TopNav"      in names
        assert "ContentCard" in names
        assert "Badge"       in names

    def test_component_includes_comp_type(self, full_screen_graph):
        result = full_screen_graph.get_screen_full("HomeScreen")
        nav    = next(c for c in result["components"] if c["name"] == "TopNav")
        assert nav["comp_type"] == "navigation"

    def test_component_includes_jsx_snippet(self, full_screen_graph):
        result = full_screen_graph.get_screen_full("HomeScreen")
        nav    = next(c for c in result["components"] if c["name"] == "TopNav")
        assert "Home" in nav["jsx_snippet"]

    def test_component_includes_styles_by_state(self, full_screen_graph):
        result       = full_screen_graph.get_screen_full("HomeScreen")
        nav          = next(c for c in result["components"] if c["name"] == "TopNav")
        default_props = {s["property"] for s in nav["styles_by_state"].get("default", [])}
        assert "display" in default_props

    def test_component_styles_grouped_by_hover_state(self, full_screen_graph):
        result = full_screen_graph.get_screen_full("HomeScreen")
        nav    = next(c for c in result["components"] if c["name"] == "TopNav")
        assert "hover" in nav["styles_by_state"]

    def test_component_includes_interactions(self, full_screen_graph):
        result = full_screen_graph.get_screen_full("HomeScreen")
        nav    = next(c for c in result["components"] if c["name"] == "TopNav")
        assert len(nav["interactions"]) >= 1
        assert nav["interactions"][0]["trigger"] == "hover"

    def test_component_includes_texts(self, full_screen_graph):
        result   = full_screen_graph.get_screen_full("HomeScreen")
        nav      = next(c for c in result["components"] if c["name"] == "TopNav")
        contents = [t["content"] for t in nav["texts"]]
        assert "Home" in contents

    def test_component_includes_props(self, full_screen_graph):
        result     = full_screen_graph.get_screen_full("HomeScreen")
        nav        = next(c for c in result["components"] if c["name"] == "TopNav")
        prop_names = {p["prop_name"] for p in nav["props"]}
        assert "title"   in prop_names
        assert "variant" in prop_names

    def test_required_prop_has_empty_default(self, full_screen_graph):
        result     = full_screen_graph.get_screen_full("HomeScreen")
        nav        = next(c for c in result["components"] if c["name"] == "TopNav")
        title_prop = next(p for p in nav["props"] if p["prop_name"] == "title")
        assert title_prop["default_value"] == ""

    def test_optional_prop_carries_default_value(self, full_screen_graph):
        result        = full_screen_graph.get_screen_full("HomeScreen")
        nav           = next(c for c in result["components"] if c["name"] == "TopNav")
        variant_prop  = next(p for p in nav["props"] if p["prop_name"] == "variant")
        assert variant_prop["default_value"] == "default"

    def test_component_includes_children(self, full_screen_graph):
        result = full_screen_graph.get_screen_full("HomeScreen")
        card   = next(c for c in result["components"] if c["name"] == "ContentCard")
        assert "Badge" in card["children"]


# ── Layout profiles ───────────────────────────────────────────────────────────

class TestGetScreenFullLayoutProfiles:
    def test_includes_layout_profiles_list(self, full_screen_graph):
        result = full_screen_graph.get_screen_full("HomeScreen")
        assert "layout_profiles" in result
        assert len(result["layout_profiles"]) > 0

    def test_layout_profile_has_component_name(self, full_screen_graph):
        result = full_screen_graph.get_screen_full("HomeScreen")
        names  = {p["component_name"] for p in result["layout_profiles"]}
        assert "TopNav" in names

    def test_layout_profile_captures_display(self, full_screen_graph):
        result = full_screen_graph.get_screen_full("HomeScreen")
        nav    = next(p for p in result["layout_profiles"] if p["component_name"] == "TopNav")
        assert nav["display"] == "flex"

    def test_layout_profile_captures_width(self, full_screen_graph):
        result = full_screen_graph.get_screen_full("HomeScreen")
        nav    = next(p for p in result["layout_profiles"] if p["component_name"] == "TopNav")
        assert nav["width"] == "100%"


# ── Query efficiency ──────────────────────────────────────────────────────────

class TestGetScreenFullQueryEfficiency:
    def test_uses_bounded_query_count_regardless_of_component_count(self, full_screen_graph, monkeypatch):
        """
        get_screen_full must issue O(1) database queries — a fixed set of JOIN
        queries, not one query per component.  With 3 components the call must
        stay well under 15 round-trips (actual target: ≤13).
        """
        call_count = 0
        original_q = full_screen_graph._q

        def counting_q(cypher, params=None):
            nonlocal call_count
            call_count += 1
            return original_q(cypher, params)

        monkeypatch.setattr(full_screen_graph, "_q", counting_q)
        full_screen_graph.get_screen_full("HomeScreen")
        assert call_count <= 13, (
            f"Expected ≤13 queries (O(1)), got {call_count}. "
            "Likely regressed to per-component queries."
        )
