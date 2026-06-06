"""
Targeted tests for GraphReader advanced query methods and edge cases.

Covers branches missed by the existing test_writer_reader.py:
  - get_screen / get_component returning None for unknown names
  - get_section with and without content
  - find_token_usage with component and screen cross-references
  - get_interactions for component with and without interactions
  - get_impact for both component and token impact paths
  - count_nodes returning all schema categories
  - _fuzzy_match suffix and contains matching
  - _q graceful handling of Kuzu errors
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import kuzu
import pytest

from design_graph.core.models import (
    DesignToken,
    ExtractedComponent,
    ExtractedScreen,
    ExtractedSection,
    InteractionEntry,
    StyleEntry,
    TextEntry,
)
from design_graph.graph.reader import GraphReader, _fuzzy_match
from design_graph.graph.schema import initialize_schema
from design_graph.graph.writer import GraphWriter
from design_graph.parsing.token_extractor import build_token_map


# ── Shared populated fixture ──────────────────────────────────────────────────

@pytest.fixture(scope="module")
def rich_graph(tmp_path_factory):
    """
    Build a graph with rich enough data to exercise all reader paths:
    - 2 tokens (color, spacing)
    - BtnPrimary with style + interaction + text
    - SectionCard (leaf)
    - CartItem (contains PriceTag)
    - PriceTag (leaf)
    - RestaurantsPage screen with Header section
    """
    tmp  = tmp_path_factory.mktemp("reader_adv")
    db   = kuzu.Database(str(tmp / "adv.db"))
    conn = kuzu.Connection(db)
    initialize_schema(conn)
    gw = GraphWriter(conn)

    color_token   = DesignToken(id="col_1", category="color",   label="primary",  value="#ffb81c", usage=8)
    spacing_token = DesignToken(id="spc_1", category="spacing", label="space_16", value="16px",    usage=4)
    gw.write_tokens([color_token, spacing_token])
    tm = build_token_map([color_token, spacing_token])

    price_tag = ExtractedComponent(
        name="PriceTag", comp_type="badge",
        jsx_snippet="<span style={{color:'#ffb81c'}}>R$99</span>",
        occurrence=3, classes="price",
        styles=[StyleEntry(id="st_price", element="PriceTag", state="default",
                           property="color", value="#ffb81c")],
        interactions=[], texts=[TextEntry(id="tx_1", content="R$99", text_type="label",
                                         source="PriceTag", element="span")],
        child_refs=[],
    )
    gw.write_component(price_tag, tm)

    cart_item = ExtractedComponent(
        name="CartItem", comp_type="card",
        jsx_snippet="<div><PriceTag /></div>",
        occurrence=2, classes="cart-item",
        styles=[StyleEntry(id="st_cart", element="CartItem", state="hover",
                           property="opacity", value="0.8")],
        interactions=[InteractionEntry(id="int_1", trigger="hover", css_prop="opacity",
                                       from_val="1", to_val="0.8", transition="all 0.2s")],
        texts=[], child_refs=["PriceTag"],
    )
    gw.write_component(cart_item, tm)

    btn = ExtractedComponent(
        name="BtnPrimary", comp_type="button",
        jsx_snippet="<button>OK</button>",
        occurrence=5, classes="btn",
        styles=[], interactions=[], texts=[], child_refs=[],
    )
    gw.write_component(btn, tm)

    section = ExtractedSection(
        id="sec_hdr", screen="RestaurantsPage", name="Header",
        styles={"padding": "16px"}, component_refs=["BtnPrimary"],
        texts=["Restaurantes"], jsx_snippet="<div>header</div>",
        detection_method="comment",
    )
    screen = ExtractedScreen(
        name="RestaurantsPage",
        component_refs=["BtnPrimary", "CartItem"],
        sections_count=1,
    )
    gw.write_screen(screen, [section], tm)

    ro_db   = kuzu.Database(str(tmp / "adv.db"), read_only=True)
    ro_conn = kuzu.Connection(ro_db)
    return SimpleNamespace(reader=GraphReader(ro_conn))


# ── get_screen ────────────────────────────────────────────────────────────────

class TestGetScreen:
    def test_returns_none_for_nonexistent_screen(self, rich_graph):
        assert rich_graph.reader.get_screen("GhostScreen999") is None

    def test_returns_dict_for_known_screen(self, rich_graph):
        result = rich_graph.reader.get_screen("RestaurantsPage")
        assert result is not None
        assert result["name"] == "RestaurantsPage"


# ── get_component ─────────────────────────────────────────────────────────────

class TestGetComponent:
    def test_returns_none_for_nonexistent_component(self, rich_graph):
        assert rich_graph.reader.get_component("NoSuchComp999") is None

    def test_returns_dict_for_known_component(self, rich_graph):
        result = rich_graph.reader.get_component("BtnPrimary")
        assert result is not None


# ── get_section ───────────────────────────────────────────────────────────────

class TestGetSection:
    def test_returns_section_by_exact_name(self, rich_graph):
        sec = rich_graph.reader.get_section("RestaurantsPage", "Header")
        assert sec is not None
        assert sec["name"] == "Header"

    def test_returns_section_by_partial_name(self, rich_graph):
        sec = rich_graph.reader.get_section("RestaurantsPage", "head")
        assert sec is not None

    def test_returns_none_for_missing_section(self, rich_graph):
        assert rich_graph.reader.get_section("RestaurantsPage", "FooterXXX") is None

    def test_section_has_detection_method(self, rich_graph):
        sec = rich_graph.reader.get_section("RestaurantsPage", "Header")
        assert sec["detection_method"] == "comment"

    def test_section_has_component_refs(self, rich_graph):
        sec = rich_graph.reader.get_section("RestaurantsPage", "Header")
        assert "BtnPrimary" in sec["component_refs"]


# ── find_token_usage ──────────────────────────────────────────────────────────

class TestFindTokenUsage:
    def test_finds_token_by_value(self, rich_graph):
        result = rich_graph.reader.find_token_usage("#ffb81c")
        assert len(result) >= 1

    def test_result_includes_components_that_use_token(self, rich_graph):
        result = rich_graph.reader.find_token_usage("#ffb81c")
        all_comp_names = [c.get("c.name") for u in result for c in u.get("components", [])]
        assert "PriceTag" in all_comp_names

    def test_finds_token_by_label(self, rich_graph):
        result = rich_graph.reader.find_token_usage("primary")
        assert len(result) >= 1

    def test_returns_empty_for_unknown_value(self, rich_graph):
        result = rich_graph.reader.find_token_usage("no_such_token_xyz")
        assert result == []

    def test_each_result_has_token_fields(self, rich_graph):
        result = rich_graph.reader.find_token_usage("#ffb81c")
        for u in result:
            assert "t.label" in u
            assert "t.value" in u
            assert "t.category" in u


# ── get_interactions ──────────────────────────────────────────────────────────

class TestGetInteractions:
    def test_returns_interactions_for_component_with_hover(self, rich_graph):
        interactions = rich_graph.reader.get_interactions("CartItem")
        assert len(interactions) >= 1
        assert any(i.get("i.trigger") == "hover" for i in interactions)

    def test_returns_empty_for_component_without_interactions(self, rich_graph):
        interactions = rich_graph.reader.get_interactions("BtnPrimary")
        assert isinstance(interactions, list)

    def test_returns_empty_for_nonexistent_component(self, rich_graph):
        interactions = rich_graph.reader.get_interactions("GhostComp999")
        assert interactions == []

    def test_interaction_has_required_fields(self, rich_graph):
        interactions = rich_graph.reader.get_interactions("CartItem")
        for i in interactions:
            assert "i.trigger"   in i
            assert "i.css_prop"  in i
            assert "i.to_val"    in i


# ── get_impact ────────────────────────────────────────────────────────────────

class TestGetImpact:
    def test_component_impact_found_true(self, rich_graph):
        result = rich_graph.reader.get_impact("BtnPrimary")
        assert result["found"] is True

    def test_component_impact_has_type_and_screens(self, rich_graph):
        result = rich_graph.reader.get_impact("BtnPrimary")
        assert "type" in result
        assert "screens" in result
        assert "RestaurantsPage" in result["screens"]

    def test_token_impact_found_via_label(self, rich_graph):
        result = rich_graph.reader.get_impact("primary")
        assert result["found"] is True
        assert "label" in result
        assert result["value"] == "#ffb81c"

    def test_token_impact_includes_components(self, rich_graph):
        result = rich_graph.reader.get_impact("primary")
        assert "components" in result
        assert "PriceTag" in result["components"]

    def test_nonexistent_name_returns_not_found(self, rich_graph):
        result = rich_graph.reader.get_impact("XyzNotHere999")
        assert result["found"] is False


# ── count_nodes ───────────────────────────────────────────────────────────────

class TestCountNodes:
    def test_returns_all_schema_keys(self, rich_graph):
        counts = rich_graph.reader.count_nodes()
        expected_keys = {"screens", "components", "tokens", "texts",
                         "styles", "sections", "interactions", "contains"}
        assert expected_keys.issubset(counts.keys())

    def test_screens_count_is_one(self, rich_graph):
        counts = rich_graph.reader.count_nodes()
        assert counts["screens"] >= 1

    def test_components_count_is_positive(self, rich_graph):
        counts = rich_graph.reader.count_nodes()
        assert counts["components"] >= 1


# ── _fuzzy_match suffix and contains ─────────────────────────────────────────

class TestFuzzyMatch:
    NAMES = ["RestaurantsPage", "BtnPrimary", "SectionCard", "LoginForm"]

    def test_exact_match_case_insensitive(self):
        assert _fuzzy_match("btnprimary", self.NAMES) == "BtnPrimary"

    def test_prefix_match(self):
        assert _fuzzy_match("Rest", self.NAMES) == "RestaurantsPage"

    def test_suffix_match(self):
        assert _fuzzy_match("Page", self.NAMES) == "RestaurantsPage"

    def test_contains_match(self):
        assert _fuzzy_match("tionCard", self.NAMES) == "SectionCard"

    def test_no_match_returns_none(self):
        assert _fuzzy_match("NoMatchXYZ", self.NAMES) is None

    def test_empty_names_returns_none(self):
        assert _fuzzy_match("anything", []) is None

    def test_empty_hint_returns_none(self):
        assert _fuzzy_match("", self.NAMES) is None


# ── _q error handling ─────────────────────────────────────────────────────────

class TestQueryErrorHandling:
    def test_invalid_cypher_returns_empty_list(self, rich_graph):
        """_q must catch Kuzu exceptions and return [] rather than raising."""
        result = rich_graph.reader._q("NOT VALID CYPHER SYNTAX !!!!")
        assert result == []
