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
    IconAsset,
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
        count = gw.write_tokens([token])
        assert count == 0
        result = conn.execute("MATCH (t:Token {id:'col_t2'}) RETURN count(t)")
        assert result.get_next()[0] == 1

    def test_duplicate_token_ids_in_same_batch_inserted_once(self, writer):
        gw, conn = writer
        tokens = [
            DesignToken(id="rx_dup", category="radius", label="radius_sm", value="8px", usage=7),
            DesignToken(id="rx_dup", category="radius", label="radius_sm", value="8px", usage=3),
        ]
        count = gw.write_tokens(tokens)
        assert count == 1
        result = conn.execute("MATCH (t:Token {id:'rx_dup'}) RETURN count(t)")
        assert result.get_next()[0] == 1


class TestWriteIcons:
    def test_inserts_icon_node(self, writer):
        gw, conn = writer
        icon = IconAsset(id="icon_aaaaaaaa", markup="<svg><path d=\"M0 0\"/></svg>")
        count = gw.write_icons([icon])
        assert count == 1
        result = conn.execute("MATCH (i:Icon {id:'icon_aaaaaaaa'}) RETURN i.markup")
        assert result.get_next()[0] == icon.markup

    def test_idempotent_duplicate(self, writer):
        gw, conn = writer
        icon = IconAsset(id="icon_bbbbbbbb", markup="<svg/>")
        gw.write_icons([icon])
        count = gw.write_icons([icon])
        assert count == 0
        result = conn.execute("MATCH (i:Icon {id:'icon_bbbbbbbb'}) RETURN count(i)")
        assert result.get_next()[0] == 1

    def test_duplicate_icon_ids_in_same_batch_inserted_once(self, writer):
        gw, conn = writer
        icons = [
            IconAsset(id="icon_cccccccc", markup="<svg/>"),
            IconAsset(id="icon_cccccccc", markup="<svg/>"),
        ]
        count = gw.write_icons(icons)
        assert count == 1
        result = conn.execute("MATCH (i:Icon {id:'icon_cccccccc'}) RETURN count(i)")
        assert result.get_next()[0] == 1


class TestWriteModuleTexts:
    """
    UIText from a module-level constant array (const DETAIL_TABS = [...])
    has no owning Component or Section — that's the whole point, it's
    text no other extractor could ever attach to one. write_module_texts
    inserts the UIText node on its own, with no COMP_HAS_TEXT/
    SECTION_HAS_TEXT edge, and it's still directly queryable exactly like
    every other UIText (list_texts/search don't require an edge).
    """

    def test_inserts_uitext_node(self, writer):
        gw, conn = writer
        text = TextEntry.create(content="Cardápio & Preço", text_type="label", source="DETAIL_TABS")
        count = gw.write_module_texts([text])
        assert count == 1
        result = conn.execute(f"MATCH (t:UIText {{id:'{text.id}'}}) RETURN t.content, t.source")
        row = result.get_next()
        assert row[0] == "Cardápio & Preço"
        assert row[1] == "DETAIL_TABS"

    def test_idempotent_duplicate(self, writer):
        gw, conn = writer
        text = TextEntry.create(content="Produção & Setores", text_type="label", source="DETAIL_TABS")
        gw.write_module_texts([text])
        count = gw.write_module_texts([text])
        assert count == 0
        result = conn.execute(f"MATCH (t:UIText {{id:'{text.id}'}}) RETURN count(t)")
        assert result.get_next()[0] == 1

    def test_findable_via_list_texts_with_no_owning_component(self, writer):
        gw, conn = writer
        text = TextEntry.create(content="Visão Geral", text_type="label", source="DETAIL_TABS")
        gw.write_module_texts([text])
        reader = GraphReader(conn)
        contents = {t["t.content"] for t in reader.list_texts()}
        assert "Visão Geral" in contents


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

    def test_existing_shell_component_does_not_warn_on_full_component_write(self, writer, caplog):
        gw, conn = writer
        screen = ExtractedScreen(name="ShellFirstPage",
                                 component_refs=["MenuFormModal"], sections_count=0)
        gw.write_screen(screen, [], {})

        gw.write_component(self._make_comp("MenuFormModal"), {})

        result = conn.execute("MATCH (c:Component {name:'MenuFormModal'}) RETURN count(c)")
        assert result.get_next()[0] == 1
        assert "duplicated primary key value MenuFormModal" not in caplog.text

        resolved = conn.execute(
            "MATCH (c:Component {name:'MenuFormModal'}) "
            "RETURN c.occurrence, c.jsx_snippet"
        ).get_next()
        assert resolved == [1, "<div/>"]

    def test_screen_reference_creates_unresolved_component_shell(self, writer):
        gw, conn = writer
        screen = ExtractedScreen(
            name="ShellPage", component_refs=["MissingCard"], sections_count=0
        )

        gw.write_screen(screen, [], {})

        occurrence = conn.execute(
            "MATCH (c:Component {name:'MissingCard'}) RETURN c.occurrence"
        ).get_next()[0]
        assert occurrence == 0

    def test_declared_screen_reference_is_not_created_as_component_shell(self, writer):
        gw, conn = writer
        dashboard = ExtractedScreen("DashboardPage", ["FreeDashboard"], 0)
        free = ExtractedScreen("FreeDashboard", [], 0)
        gw.declare_screens([dashboard, free])

        gw.write_screen(dashboard, [], {})

        component_count = conn.execute(
            "MATCH (c:Component {name:'FreeDashboard'}) RETURN count(c)"
        ).get_next()[0]
        screen_links = conn.execute(
            "MATCH (:Screen {name:'DashboardPage'})-[:USES_SCREEN]->"
            "(:Screen {name:'FreeDashboard'}) RETURN count(*)"
        ).get_next()[0]
        assert component_count == 0
        assert screen_links == 1

    def test_section_can_reference_declared_screen(self, writer):
        gw, conn = writer
        parent = ExtractedScreen("RestaurantDetail", [], 1)
        child = ExtractedScreen("RestaurantSectorsView", [], 0)
        section = ExtractedSection(
            id="sectors", screen="RestaurantDetail", name="Sectors", styles={},
            component_refs=["RestaurantSectorsView"], texts=[], jsx_snippet="<div/>",
            detection_method="semantic",
        )
        gw.declare_screens([parent, child])

        gw.write_screen(parent, [section], {})

        links = conn.execute(
            "MATCH (:Section {id:'sectors'})-[:SECTION_USES_SCREEN]->"
            "(:Screen {name:'RestaurantSectorsView'}) RETURN count(*)"
        ).get_next()[0]
        assert links == 1

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

    def test_distinguishes_extracted_and_unresolved_components(self, writer):
        gw, _ = writer
        gw.write_component(TestWriteComponent()._make_comp("KnownCard"), {})
        gw.write_screen(
            ExtractedScreen("ShellPage", ["KnownCard", "MissingCard"], 0), [], {}
        )

        stats = gw.get_stats()

        assert stats["components"] == 2
        assert stats["extracted_components"] == 1
        assert stats["unresolved_components"] == 1


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


@pytest.fixture
def two_screen_db(tmp_path):
    """
    Two screens, each using a component styled with a different token, so
    get_tokens(screen=...) has something real to distinguish:
    - Token 'primary' (#ffb81c) → Component BtnWithBadge → Screen RestaurantsPage
    - Token 'dark' (#111111)    → Component DarkCard      → Screen OrdersPage
    """
    db = kuzu.Database(str(tmp_path / "two_screen.db"))
    conn = kuzu.Connection(db)
    initialize_schema(conn)
    gw = GraphWriter(conn)

    primary = DesignToken(id="col_primary", category="color", label="primary", value="#ffb81c", usage=5)
    dark = DesignToken(id="col_dark", category="color", label="dark", value="#111111", usage=3)
    gw.write_tokens([primary, dark])
    tm = build_token_map([primary, dark])

    btn = ExtractedComponent(
        name="BtnWithBadge", comp_type="button", jsx_snippet="<button/>",
        occurrence=1, classes="", child_refs=[],
        styles=[StyleEntry(id="st_primary", element="BtnWithBadge", state="default",
                           property="backgroundColor", value="#ffb81c")],
        interactions=[], texts=[],
    )
    gw.write_component(btn, tm)

    dark_card = ExtractedComponent(
        name="DarkCard", comp_type="card", jsx_snippet="<div/>",
        occurrence=1, classes="", child_refs=[],
        styles=[StyleEntry(id="st_dark", element="DarkCard", state="default",
                           property="backgroundColor", value="#111111")],
        interactions=[], texts=[],
    )
    gw.write_component(dark_card, tm)

    restaurants = ExtractedScreen(name="RestaurantsPage", component_refs=["BtnWithBadge"], sections_count=0)
    orders = ExtractedScreen(name="OrdersPage", component_refs=["DarkCard"], sections_count=0)
    gw.write_screen(restaurants, [], tm)
    gw.write_screen(orders, [], tm)

    ro_db = kuzu.Database(str(tmp_path / "two_screen.db"), read_only=True)
    ro_conn = kuzu.Connection(ro_db)
    return GraphReader(ro_conn)


class TestGetTokensScopedByScreen:
    """
    get_tokens() with no scope is one global list ranked by prototype-wide
    frequency — useful for "what colors exist", useless for "what's the
    canvas of screen X" once dozens of unrelated screens share one
    catalog. screen= narrows to tokens actually reachable from that
    screen's own components, via the same USES_COMPONENT → CONTAINS*
    closure find_token_usage already uses for its screen listing.
    """

    def test_no_screen_returns_every_token(self, two_screen_db):
        labels = {t["t.label"] for t in two_screen_db.get_tokens()}
        assert labels == {"primary", "dark"}

    def test_screen_scope_includes_only_its_own_tokens(self, two_screen_db):
        labels = {t["t.label"] for t in two_screen_db.get_tokens(screen="RestaurantsPage")}
        assert labels == {"primary"}

    def test_other_screen_scope_excludes_it(self, two_screen_db):
        labels = {t["t.label"] for t in two_screen_db.get_tokens(screen="OrdersPage")}
        assert labels == {"dark"}

    def test_unknown_screen_returns_no_tokens(self, two_screen_db):
        assert two_screen_db.get_tokens(screen="NoSuchScreen") == []

    def test_screen_scope_composes_with_category(self, two_screen_db):
        labels = {t["t.label"] for t in two_screen_db.get_tokens(category="color", screen="RestaurantsPage")}
        assert labels == {"primary"}


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


# ── JSX snippet size cap ───────────────────────────────────────────────────────

class TestJsxSnippetSizeCap:
    """
    GraphWriter must cap jsx_snippet before persisting so that oversized JSX
    cannot cause performance issues or exceed Kuzu string limits.
    The cap must be enforced in write_component AND write_screen (sections).
    """

    @pytest.fixture()
    def fresh_writer(self, tmp_path):
        from types import SimpleNamespace
        import kuzu
        from design_graph.graph.schema import initialize_schema
        from design_graph.graph.writer import GraphWriter
        from design_graph.graph.reader import GraphReader
        db   = kuzu.Database(str(tmp_path / "cap.db"))
        conn = kuzu.Connection(db)
        initialize_schema(conn)
        # Use same connection for writer and reader — avoids two-instance locking
        return SimpleNamespace(writer=GraphWriter(conn), reader=GraphReader(conn))

    def _oversized_jsx(self) -> str:
        return "<div>" + ("x" * 30_000) + "</div>"

    def test_oversized_component_jsx_is_capped(self, fresh_writer):
        from design_graph.core.models import ExtractedComponent
        from design_graph.core.constants import MAX_JSX_SNIPPET_CHARS
        comp = ExtractedComponent(
            name="BigComp", comp_type="card", jsx_snippet=self._oversized_jsx(),
            occurrence=1, classes="", styles=[], interactions=[], texts=[], child_refs=[],
        )
        fresh_writer.writer.write_component(comp, {})
        result = fresh_writer.reader.get_component("BigComp")
        assert result is not None
        stored = result.get("c.jsx_snippet", "")
        assert len(stored) <= MAX_JSX_SNIPPET_CHARS, (
            f"Stored jsx_snippet has {len(stored)} chars, expected ≤ {MAX_JSX_SNIPPET_CHARS}"
        )

    def test_oversized_section_jsx_is_capped(self, fresh_writer):
        from design_graph.core.models import ExtractedScreen, ExtractedSection
        from design_graph.core.constants import MAX_JSX_SNIPPET_CHARS
        section = ExtractedSection(
            id="sec_big", screen="BigPage", name="BigSection",
            styles={}, component_refs=[], texts=[],
            jsx_snippet=self._oversized_jsx(), detection_method="comment",
        )
        screen = ExtractedScreen(name="BigPage", component_refs=[], sections_count=1)
        fresh_writer.writer.write_screen(screen, [section], {})
        sec = fresh_writer.reader.get_section("BigPage", "BigSection")
        assert sec is not None
        stored = sec.get("jsx_snippet", "")
        assert len(stored) <= MAX_JSX_SNIPPET_CHARS, (
            f"Stored section jsx_snippet has {len(stored)} chars, expected ≤ {MAX_JSX_SNIPPET_CHARS}"
        )

    def test_normal_jsx_is_stored_intact(self, fresh_writer):
        from design_graph.core.models import ExtractedComponent
        jsx = "<div><button>OK</button></div>"
        comp = ExtractedComponent(
            name="SmallComp", comp_type="button", jsx_snippet=jsx,
            occurrence=1, classes="", styles=[], interactions=[], texts=[], child_refs=[],
        )
        fresh_writer.writer.write_component(comp, {})
        result = fresh_writer.reader.get_component("SmallComp")
        assert result["c.jsx_snippet"] == jsx

    def test_oversized_screen_jsx_is_capped(self, fresh_writer):
        from design_graph.core.models import ExtractedScreen
        from design_graph.core.constants import MAX_JSX_SNIPPET_CHARS
        screen = ExtractedScreen(
            name="BigScreen", component_refs=[], sections_count=0,
            jsx_snippet=self._oversized_jsx(),
        )
        fresh_writer.writer.declare_screens([screen])
        stored = fresh_writer.reader.get_full_jsx("BigScreen")
        assert stored.startswith("<div>"), "screen fallback did not return the stored jsx_snippet at all"
        assert len(stored) <= MAX_JSX_SNIPPET_CHARS, (
            f"Stored screen jsx_snippet has {len(stored)} chars, expected ≤ {MAX_JSX_SNIPPET_CHARS}"
        )


class TestGetFullJsxFallsBackToScreen:
    """
    get_full_jsx('ItemEditorV6') failed outright before this: a full-page
    overlay shell is classified as a Screen and (deliberately) never also
    extracted as a Component, so a Component-only lookup always came up
    empty for it. get_full_jsx must resolve a Screen's own jsx_snippet
    when no Component of that name exists — not report the screen's shell
    JSX as "unavailable" when it was captured, just filed differently.
    """

    @pytest.fixture()
    def fresh_writer(self, tmp_path):
        db = kuzu.Database(str(tmp_path / "screen_jsx.db"))
        conn = kuzu.Connection(db)
        initialize_schema(conn)
        return SimpleNamespace(writer=GraphWriter(conn), reader=GraphReader(conn))

    def test_screen_without_matching_component_returns_its_own_jsx(self, fresh_writer):
        screen = ExtractedScreen(
            name="ItemEditorV6", component_refs=["BasicTab"], sections_count=0,
            jsx_snippet="<div className='shell'>{tab === 'basic' && <BasicTab />}</div>",
        )
        fresh_writer.writer.declare_screens([screen])
        result = fresh_writer.reader.get_full_jsx("ItemEditorV6")
        assert "shell" in result
        assert "BasicTab" in result

    def test_component_of_same_name_still_takes_precedence(self, fresh_writer):
        # A name that resolves to a real Component (the common case) must
        # keep returning the Component's JSX unchanged — the Screen
        # fallback only fires when no Component matches at all.
        comp = ExtractedComponent(
            name="PricingPageV6", comp_type="card", jsx_snippet="<div>component version</div>",
            occurrence=1, classes="", styles=[], interactions=[], texts=[], child_refs=[],
        )
        fresh_writer.writer.write_component(comp, {})
        screen = ExtractedScreen(
            name="PricingPageV6", component_refs=[], sections_count=0,
            jsx_snippet="<div>should not surface</div>",
        )
        fresh_writer.writer.declare_screens([screen])
        result = fresh_writer.reader.get_full_jsx("PricingPageV6")
        assert result == "<div>component version</div>"

    def test_unknown_name_still_returns_empty(self, fresh_writer):
        assert fresh_writer.reader.get_full_jsx("NoSuchThing") == ""
