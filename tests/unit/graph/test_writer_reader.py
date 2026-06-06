"""Tests for graph/writer.py and graph/reader.py — T10 and T11."""

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
from design_graph.graph.reader import GraphReader
from design_graph.graph.schema import initialize_schema
from design_graph.graph.writer import GraphWriter
from design_graph.parsing.token_extractor import build_token_map


# ── Shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def db_conn(tmp_path):
    db = kuzu.Database(str(tmp_path / "w.db"))
    conn = kuzu.Connection(db)
    initialize_schema(conn)
    return conn


@pytest.fixture
def writer(db_conn):
    return GraphWriter(db_conn), db_conn


@pytest.fixture
def populated_db(tmp_path):
    """
    Minimal populated database:
    - Token: primary=#ffb81c
    - Components: Badge (leaf), BtnWithBadge (contains Badge), SectionCard
    - Screen: RestaurantsPage (uses SectionCard, BtnWithBadge)
    - Section: Header (uses BtnWithBadge)
    """
    db = kuzu.Database(str(tmp_path / "p.db"))
    conn = kuzu.Connection(db)
    initialize_schema(conn)
    gw = GraphWriter(conn)

    token = DesignToken(id="col_1", category="color",
                        label="primary", value="#ffb81c", usage=5)
    gw.write_tokens([token])
    tm = build_token_map([token])

    badge = ExtractedComponent(
        name="Badge", comp_type="badge", jsx_snippet="<span>badge</span>",
        occurrence=3, classes="badge", styles=[], interactions=[], texts=[], child_refs=[],
    )
    gw.write_component(badge, tm)

    btn = ExtractedComponent(
        name="BtnWithBadge", comp_type="button",
        jsx_snippet="<button><Badge /></button>",
        occurrence=2, classes="btn", child_refs=["Badge"],
        styles=[StyleEntry(id="st_1", element="BtnWithBadge", state="default",
                           property="backgroundColor", value="#ffb81c")],
        interactions=[], texts=[],
    )
    gw.write_component(btn, tm)

    card = ExtractedComponent(
        name="SectionCard", comp_type="card", jsx_snippet="<div>card</div>",
        occurrence=4, classes="card", styles=[], interactions=[], texts=[], child_refs=[],
    )
    gw.write_component(card, tm)

    section = ExtractedSection(
        id="sec_hdr", screen="RestaurantsPage", name="Header",
        styles={}, component_refs=["BtnWithBadge"], texts=["Restaurantes"],
        jsx_snippet="<div>header</div>", detection_method="comment",
    )
    screen = ExtractedScreen(
        name="RestaurantsPage",
        component_refs=["SectionCard", "BtnWithBadge"],
        sections_count=1,
    )
    gw.write_screen(screen, [section], tm)

    # Re-open read-only for the reader
    ro_db = kuzu.Database(str(tmp_path / "p.db"), read_only=True)
    ro_conn = kuzu.Connection(ro_db)
    return SimpleNamespace(reader=GraphReader(ro_conn), writer=gw)


# ── Writer tests ──────────────────────────────────────────────────────────────

class TestWriteTokens:
    def test_inserts_token_node(self, writer):
        gw, conn = writer
        token = DesignToken(id="col_t1", category="color",
                            label="test", value="#aabbcc", usage=2)
        count = gw.write_tokens([token])
        assert count == 1
        result = conn.execute("MATCH (t:Token {id:'col_t1'}) RETURN t.label")
        assert result.get_next()[0] == "test"

    def test_idempotent_duplicate(self, writer):
        gw, conn = writer
        token = DesignToken(id="col_t2", category="color",
                            label="x", value="#112233", usage=1)
        gw.write_tokens([token])
        gw.write_tokens([token])
        result = conn.execute("MATCH (t:Token {id:'col_t2'}) RETURN count(t)")
        assert result.get_next()[0] == 1


class TestWriteComponent:
    def _make_comp(self, name, child_refs=None):
        return ExtractedComponent(
            name=name, comp_type="card", jsx_snippet="<div/>",
            occurrence=1, classes="", styles=[], interactions=[],
            texts=[], child_refs=child_refs or [],
        )

    def test_inserts_component_node(self, writer):
        gw, conn = writer
        gw.write_component(self._make_comp("TestComp"), {})
        result = conn.execute("MATCH (c:Component {name:'TestComp'}) RETURN c.name")
        assert result.get_next()[0] == "TestComp"

    def test_idempotent_on_duplicate(self, writer):
        gw, conn = writer
        gw.write_component(self._make_comp("DupComp"), {})
        gw.write_component(self._make_comp("DupComp"), {})
        result = conn.execute("MATCH (c:Component {name:'DupComp'}) RETURN count(c)")
        assert result.get_next()[0] == 1

    def test_creates_contains_relation(self, writer):
        gw, conn = writer
        gw.write_component(self._make_comp("ChildComp"), {})
        gw.write_component(self._make_comp("ParentComp", child_refs=["ChildComp"]), {})
        result = conn.execute(
            "MATCH (p:Component {name:'ParentComp'})-[:CONTAINS]->(c:Component) "
            "RETURN c.name"
        )
        assert result.get_next()[0] == "ChildComp"

    def test_contains_not_created_for_missing_child(self, writer):
        gw, conn = writer
        gw.write_component(self._make_comp("OrphanParent", child_refs=["Nonexistent"]), {})
        result = conn.execute("MATCH ()-[:CONTAINS]->() RETURN count(*)")
        assert result.get_next()[0] == 0

    def test_style_linked_to_component(self, writer):
        gw, conn = writer
        comp = ExtractedComponent(
            name="StyledComp", comp_type="button", jsx_snippet="",
            occurrence=1, classes="",
            styles=[StyleEntry(id="st_sc1", element="StyledComp",
                               state="default", property="color", value="red")],
            interactions=[], texts=[], child_refs=[],
        )
        gw.write_component(comp, {})
        result = conn.execute(
            "MATCH (c:Component {name:'StyledComp'})-[:HAS_STYLE]->(s:Style) "
            "RETURN s.property"
        )
        assert result.get_next()[0] == "color"

    def test_token_rel_created_on_style_value_match(self, writer):
        gw, conn = writer
        token = DesignToken(id="col_x", category="color",
                            label="primary", value="#ffb81c", usage=5)
        gw.write_tokens([token])
        tm = build_token_map([token])
        comp = ExtractedComponent(
            name="TokenComp", comp_type="button", jsx_snippet="",
            occurrence=1, classes="",
            styles=[StyleEntry(id="st_tok1", element="TokenComp",
                               state="default", property="bg", value="#ffb81c")],
            interactions=[], texts=[], child_refs=[],
        )
        gw.write_component(comp, tm)
        result = conn.execute(
            "MATCH (c:Component {name:'TokenComp'})-[:USES_TOKEN]->(t:Token) "
            "RETURN t.label"
        )
        assert result.get_next()[0] == "primary"


class TestWriteScreen:
    def test_inserts_screen_node(self, writer):
        gw, conn = writer
        screen = ExtractedScreen(name="TestPage", component_refs=[], sections_count=0)
        gw.write_screen(screen, [], {})
        result = conn.execute("MATCH (s:Screen {name:'TestPage'}) RETURN s.name")
        assert result.get_next()[0] == "TestPage"

    def test_creates_shell_for_unknown_ref(self, writer):
        gw, conn = writer
        screen = ExtractedScreen(name="ShellPage",
                                 component_refs=["UnknownWidget"], sections_count=0)
        gw.write_screen(screen, [], {})
        result = conn.execute(
            "MATCH (c:Component {name:'UnknownWidget'}) RETURN c.jsx_snippet"
        )
        assert result.get_next()[0] == ""

    def test_section_linked_to_screen(self, writer):
        gw, conn = writer
        screen = ExtractedScreen(name="SectionPage", component_refs=[], sections_count=1)
        section = ExtractedSection(
            id="sec_t1", screen="SectionPage", name="Header",
            styles={}, component_refs=[], texts=[], jsx_snippet="<div/>",
            detection_method="comment",
        )
        gw.write_screen(screen, [section], {})
        result = conn.execute(
            "MATCH (s:Screen {name:'SectionPage'})-[:HAS_SECTION]->(sec:Section) "
            "RETURN sec.name"
        )
        assert result.get_next()[0] == "Header"


class TestGetStats:
    def test_all_keys_present(self, writer):
        gw, _ = writer
        stats = gw.get_stats()
        for key in ("screens", "components", "tokens", "contains"):
            assert key in stats

    def test_empty_db_all_zeros(self, writer):
        gw, _ = writer
        stats = gw.get_stats()
        assert all(v == 0 for v in stats.values())


# ── Reader tests ──────────────────────────────────────────────────────────────

class TestListScreens:
    def test_returns_all_screens(self, populated_db):
        screens = populated_db.reader.list_screens()
        names = {s["name"] for s in screens}
        assert "RestaurantsPage" in names

    def test_returns_component_count(self, populated_db):
        screens = populated_db.reader.list_screens()
        pg = next(s for s in screens if s["name"] == "RestaurantsPage")
        assert "component_count" in pg

    def test_returns_sections_count(self, populated_db):
        screens = populated_db.reader.list_screens()
        pg = next(s for s in screens if s["name"] == "RestaurantsPage")
        assert "sections_count" in pg

    def test_top_components_field_present(self, populated_db):
        screens = populated_db.reader.list_screens()
        pg = next(s for s in screens if s["name"] == "RestaurantsPage")
        assert "top_components" in pg

    def test_top_components_contains_screen_members(self, populated_db):
        screens = populated_db.reader.list_screens()
        pg = next(s for s in screens if s["name"] == "RestaurantsPage")
        # RestaurantsPage uses SectionCard and BtnWithBadge
        all_comps = set(pg["top_components"])
        assert all_comps & {"SectionCard", "BtnWithBadge"}

    def test_top_components_capped_at_five(self, populated_db):
        screens = populated_db.reader.list_screens()
        for s in screens:
            assert len(s["top_components"]) <= 5


class TestGetScreen:
    def test_exact_name_match(self, populated_db):
        screen = populated_db.reader.get_screen("RestaurantsPage")
        assert screen is not None
        assert screen["name"] == "RestaurantsPage"

    def test_fuzzy_prefix_match(self, populated_db):
        screen = populated_db.reader.get_screen("Restaurants")
        assert screen is not None
        assert screen["name"] == "RestaurantsPage"

    def test_none_for_unknown(self, populated_db):
        assert populated_db.reader.get_screen("Nonexistent") is None

    def test_includes_sections(self, populated_db):
        screen = populated_db.reader.get_screen("RestaurantsPage")
        assert "sections" in screen
        assert len(screen["sections"]) >= 1


class TestGetComponentChildren:
    def test_returns_direct_children(self, populated_db):
        children = populated_db.reader.get_component_children("BtnWithBadge")
        assert "Badge" in children

    def test_returns_empty_for_leaf(self, populated_db):
        children = populated_db.reader.get_component_children("Badge")
        assert children == []

    def test_returns_empty_for_unknown(self, populated_db):
        assert populated_db.reader.get_component_children("Ghost") == []


class TestGetComponentParents:
    def test_returns_parent_of_badge(self, populated_db):
        parents = populated_db.reader.get_component_parents("Badge")
        assert "BtnWithBadge" in parents

    def test_returns_empty_for_root_component(self, populated_db):
        parents = populated_db.reader.get_component_parents("SectionCard")
        assert parents == []


class TestFindScreensTransitively:
    """C07 — Fix: USES_COMPONENT + CONTAINS*0..3 traversal.

    populated_db graph:
      RestaurantsPage -[USES_COMPONENT]-> BtnWithBadge -[CONTAINS]-> Badge
      RestaurantsPage -[USES_COMPONENT]-> SectionCard
    """

    def test_direct_component_found(self, populated_db):
        screens = populated_db.reader.find_screens_using_comp_transitively("SectionCard")
        assert "RestaurantsPage" in screens

    def test_child_component_found_via_contains(self, populated_db):
        # BtnWithBadge is in RestaurantsPage; Badge is inside BtnWithBadge
        screens = populated_db.reader.find_screens_using_comp_transitively("Badge")
        assert "RestaurantsPage" in screens

    def test_unknown_component_returns_empty(self, populated_db):
        assert populated_db.reader.find_screens_using_comp_transitively("GhostComp") == []

    def test_result_is_list_of_strings(self, populated_db):
        result = populated_db.reader.find_screens_using_comp_transitively("Badge")
        assert isinstance(result, list)
        assert all(isinstance(s, str) for s in result)

    def test_result_is_sorted(self, populated_db):
        result = populated_db.reader.find_screens_using_comp_transitively("SectionCard")
        assert result == sorted(result)

    def test_no_duplicate_screens(self, populated_db):
        result = populated_db.reader.find_screens_using_comp_transitively("Badge")
        assert len(result) == len(set(result))


class TestGetImpact:
    def test_component_impact_has_screens(self, populated_db):
        impact = populated_db.reader.get_impact("SectionCard")
        assert impact.get("found") is True
        assert "RestaurantsPage" in impact["screens"]

    def test_unknown_name_returns_not_found(self, populated_db):
        impact = populated_db.reader.get_impact("DoesNotExist")
        assert impact.get("found") is False
