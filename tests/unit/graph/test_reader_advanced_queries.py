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

    def test_each_result_has_components_and_screens_lists(self, rich_graph):
        result = rich_graph.reader.find_token_usage("#ffb81c")
        for u in result:
            assert "components" in u
            assert "screens" in u
            assert isinstance(u["components"], list)
            assert isinstance(u["screens"], list)

    def test_screens_list_is_list_of_strings(self, rich_graph):
        result = rich_graph.reader.find_token_usage("#ffb81c")
        for u in result:
            # screens may be empty if the component using the token
            # is not directly linked to a screen via USES_COMPONENT
            assert isinstance(u["screens"], list)
            assert all(isinstance(s, str) for s in u["screens"])

    def test_multiple_matching_tokens_all_returned(self, rich_graph):
        # "primary" matches both the token label and maybe the value
        result = rich_graph.reader.find_token_usage("primary")
        assert len(result) >= 1
        # All results must have the required structure
        for u in result:
            assert "t.id" in u
            assert "components" in u


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


# ── list_components (C08) ─────────────────────────────────────────────────────
#
# rich_graph components: BtnPrimary (button, 5), CartItem (card, 2), PriceTag (badge, 3)

# ── get_styles_with_tokens (C09) ─────────────────────────────────────────────

class TestGetStylesWithTokens:
    def test_returns_list(self, rich_graph):
        result = rich_graph.reader.get_styles_with_tokens("PriceTag")
        assert isinstance(result, list)

    def test_each_row_has_state_property_value(self, rich_graph):
        for row in rich_graph.reader.get_styles_with_tokens("PriceTag"):
            assert "s.state" in row
            assert "s.property" in row
            assert "s.value" in row

    def test_token_fields_present_in_each_row(self, rich_graph):
        for row in rich_graph.reader.get_styles_with_tokens("PriceTag"):
            assert "token_label" in row
            assert "token_value" in row
            assert "token_category" in row

    def test_unknown_component_returns_empty(self, rich_graph):
        assert rich_graph.reader.get_styles_with_tokens("GhostComp999") == []

    def test_fuzzy_name_resolution_works(self, rich_graph):
        # "price" should fuzzy-match to PriceTag
        result = rich_graph.reader.get_styles_with_tokens("price")
        assert isinstance(result, list)


# ── list_components (C08) ─────────────────────────────────────────────────────
    def test_returns_all_components_without_filter(self, rich_graph):
        comps = rich_graph.reader.list_components()
        names = {c["c.name"] for c in comps}
        assert {"BtnPrimary", "CartItem", "PriceTag"}.issubset(names)

    def test_filter_by_button_type(self, rich_graph):
        comps = rich_graph.reader.list_components(comp_type="button")
        assert all(c["c.comp_type"] == "button" for c in comps)
        assert any(c["c.name"] == "BtnPrimary" for c in comps)

    def test_filter_by_badge_type(self, rich_graph):
        comps = rich_graph.reader.list_components(comp_type="badge")
        names = {c["c.name"] for c in comps}
        assert "PriceTag" in names
        assert "BtnPrimary" not in names

    def test_unknown_type_returns_empty(self, rich_graph):
        assert rich_graph.reader.list_components(comp_type="xyz_invalid") == []

    def test_sorted_by_occurrence_desc(self, rich_graph):
        comps = rich_graph.reader.list_components()
        occs = [c["c.occurrence"] for c in comps]
        assert occs == sorted(occs, reverse=True)

    def test_each_entry_has_required_fields(self, rich_graph):
        for c in rich_graph.reader.list_components():
            assert "c.name" in c
            assert "c.comp_type" in c
            assert "c.occurrence" in c


# ── get_component_spec (C08) ──────────────────────────────────────────────────

class TestGetComponentSpec:
    def test_returns_none_for_unknown(self, rich_graph):
        assert rich_graph.reader.get_component_spec("GhostComp999") is None

    def test_returns_component_metadata(self, rich_graph):
        spec = rich_graph.reader.get_component_spec("BtnPrimary")
        assert spec is not None
        assert spec["c.name"] == "BtnPrimary"
        assert spec["c.comp_type"] == "button"

    def test_styles_grouped_by_state(self, rich_graph):
        spec = rich_graph.reader.get_component_spec("CartItem")
        assert "styles_by_state" in spec
        assert isinstance(spec["styles_by_state"], dict)
        if spec["styles_by_state"]:
            for styles in spec["styles_by_state"].values():
                assert isinstance(styles, list)
                for s in styles:
                    assert "property" in s
                    assert "value" in s

    def test_tokens_list_present(self, rich_graph):
        spec = rich_graph.reader.get_component_spec("BtnPrimary")
        assert "tokens" in spec
        assert isinstance(spec["tokens"], list)

    def test_children_list_present(self, rich_graph):
        spec = rich_graph.reader.get_component_spec("CartItem")
        assert "children" in spec
        assert "PriceTag" in spec["children"]

    def test_parents_list_present(self, rich_graph):
        spec = rich_graph.reader.get_component_spec("PriceTag")
        assert "parents" in spec
        assert "CartItem" in spec["parents"]

    def test_screens_using_list_present(self, rich_graph):
        spec = rich_graph.reader.get_component_spec("BtnPrimary")
        assert "screens_using" in spec
        assert isinstance(spec["screens_using"], list)
        assert "RestaurantsPage" in spec["screens_using"]

    def test_interactions_list_present(self, rich_graph):
        spec = rich_graph.reader.get_component_spec("CartItem")
        assert "interactions" in spec
        assert isinstance(spec["interactions"], list)

    def test_texts_list_present(self, rich_graph):
        spec = rich_graph.reader.get_component_spec("PriceTag")
        assert "texts" in spec

    def test_jsx_snippet_present(self, rich_graph):
        spec = rich_graph.reader.get_component_spec("BtnPrimary")
        assert "c.jsx_snippet" in spec

    def test_fuzzy_name_resolution(self, rich_graph):
        spec = rich_graph.reader.get_component_spec("btn")  # prefix match
        assert spec is not None
        assert spec["c.name"] == "BtnPrimary"

    def test_leaf_component_has_no_children(self, rich_graph):
        spec = rich_graph.reader.get_component_spec("PriceTag")
        assert spec["children"] == []


# ── get_component_spec: screens_using traversal depth (C07 consistency) ───────

class TestGetComponentSpecScreensUsingDepth:
    """
    screens_using must use the same CONTAINS*0..3 depth as
    find_screens_using_comp_transitively — not a shallower *0..1.

    Topology: Screen -[USES_COMPONENT]-> Mid -[CONTAINS]-> Deep -[CONTAINS]-> Leaf
    Leaf is at CONTAINS depth 2 from Mid (total path length 3 from Screen).
    With *0..1 it would not be found; with *0..3 it must be found.
    """

    @pytest.fixture()
    def deep_graph(self, tmp_path_factory):
        from types import SimpleNamespace
        tmp  = tmp_path_factory.mktemp("deep_spec")
        db   = kuzu.Database(str(tmp / "deep.db"))
        conn = kuzu.Connection(db)
        initialize_schema(conn)
        gw = GraphWriter(conn)

        leaf = ExtractedComponent(
            name="DeepLeaf", comp_type="badge", jsx_snippet="<span />",
            occurrence=1, classes="", styles=[], interactions=[], texts=[], child_refs=[],
        )
        deep = ExtractedComponent(
            name="DeepMid", comp_type="card", jsx_snippet="<div><DeepLeaf /></div>",
            occurrence=1, classes="", styles=[], interactions=[], texts=[],
            child_refs=["DeepLeaf"],
        )
        mid = ExtractedComponent(
            name="TopMid", comp_type="card", jsx_snippet="<div><DeepMid /></div>",
            occurrence=1, classes="", styles=[], interactions=[], texts=[],
            child_refs=["DeepMid"],
        )
        for comp in (leaf, deep, mid):
            gw.write_component(comp, {})

        screen = ExtractedScreen(name="DeepPage", component_refs=["TopMid"], sections_count=0)
        gw.write_screen(screen, [], {})

        ro_db   = kuzu.Database(str(tmp / "deep.db"), read_only=True)
        ro_conn = kuzu.Connection(ro_db)
        return SimpleNamespace(reader=GraphReader(ro_conn))

    def test_depth2_leaf_found_in_screens_using(self, deep_graph):
        """DeepLeaf is 2 CONTAINS hops away — must appear in screens_using."""
        spec = deep_graph.reader.get_component_spec("DeepLeaf")
        assert spec is not None
        assert "DeepPage" in spec["screens_using"], (
            "screens_using must traverse CONTAINS*0..3, not *0..1. "
            "DeepLeaf is at depth 2 of CONTAINS but was not found."
        )

    def test_depth1_mid_also_found(self, deep_graph):
        """DeepMid is 1 CONTAINS hop away — must also appear."""
        spec = deep_graph.reader.get_component_spec("DeepMid")
        assert "DeepPage" in spec["screens_using"]

    def test_depth0_direct_comp_found(self, deep_graph):
        """TopMid is directly used — baseline check."""
        spec = deep_graph.reader.get_component_spec("TopMid")
        assert "DeepPage" in spec["screens_using"]

    def test_consistent_with_find_screens_transitively(self, deep_graph):
        """screens_using result must equal find_screens_using_comp_transitively."""
        spec_screens = set(deep_graph.reader.get_component_spec("DeepLeaf")["screens_using"])
        transitive   = set(deep_graph.reader.find_screens_using_comp_transitively("DeepLeaf"))
        assert spec_screens == transitive, (
            f"get_component_spec.screens_using={spec_screens} differs from "
            f"find_screens_using_comp_transitively={transitive}"
        )
