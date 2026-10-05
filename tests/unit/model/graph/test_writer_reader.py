"""Tests for graph/writer.py and graph/reader.py — T10 and T11."""

import json
from types import SimpleNamespace

import kuzu
import pytest

from tests.support.graph import writer_and_reader
from design_graph.model.entities import (
    DesignToken,
    ExtractedComponent,
    ExtractedScreen,
    ExtractedSection,
    IconAsset,
    InteractionEntry,
    StyleEntry,
    TextEntry,
)
from design_graph.model.graph.reader import GraphReader
from design_graph.model.graph.schema import initialize_schema
from design_graph.model.graph.writer import GraphWriter


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

    badge = ExtractedComponent(
        name="Badge", comp_type="badge", source_code="<span>badge</span>",
        occurrence=3, classes="badge", styles=[], interactions=[], texts=[], child_refs=[],
    )
    gw.write_component(badge)

    btn = ExtractedComponent(
        name="BtnWithBadge", comp_type="button",
        source_code="<button><Badge /></button>",
        occurrence=2, classes="btn", child_refs=["Badge"],
        styles=[StyleEntry(id="st_1", element="BtnWithBadge", state="default",
                           property="backgroundColor", value="#ffb81c")],
        interactions=[], texts=[],
    )
    gw.write_component(btn)

    card = ExtractedComponent(
        name="SectionCard", comp_type="card", source_code="<div>card</div>",
        occurrence=4, classes="card", styles=[], interactions=[], texts=[], child_refs=[],
    )
    gw.write_component(card)

    section = ExtractedSection(
        id="sec_hdr", screen="RestaurantsPage", name="Header",
        styles={}, component_refs=["BtnWithBadge"], texts=["Restaurantes"],
        source_code="<div>header</div>", detection_method="comment",
    )
    screen = ExtractedScreen(
        name="RestaurantsPage",
        component_refs=["SectionCard", "BtnWithBadge"],
        sections_count=1,
    )
    gw.write_screen(screen, [section])

    # Re-open read-only for the reader
    gw.commit()
    gw.commit()
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
        gw.commit()
        assert count == 1
        result = conn.execute("MATCH (t:Token {id:'col_t1'}) RETURN t.label")
        assert result.get_next()[0] == "test"

    def test_idempotent_duplicate(self, writer):
        gw, conn = writer
        token = DesignToken(id="col_t2", category="color",
                            label="x", value="#112233", usage=1)
        gw.write_tokens([token])
        count = gw.write_tokens([token])
        gw.commit()
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
        gw.commit()
        assert count == 1
        result = conn.execute("MATCH (t:Token {id:'rx_dup'}) RETURN count(t)")
        assert result.get_next()[0] == 1


class TestWriteIcons:
    def test_inserts_icon_node(self, writer):
        gw, conn = writer
        icon = IconAsset(id="icon_aaaaaaaa", markup="<svg><path d=\"M0 0\"/></svg>")
        count = gw.write_icons([icon])
        gw.commit()
        assert count == 1
        result = conn.execute("MATCH (i:Icon {id:'icon_aaaaaaaa'}) RETURN i.markup")
        assert result.get_next()[0] == icon.markup

    def test_idempotent_duplicate(self, writer):
        gw, conn = writer
        icon = IconAsset(id="icon_bbbbbbbb", markup="<svg/>")
        gw.write_icons([icon])
        count = gw.write_icons([icon])
        gw.commit()
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
        gw.commit()
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
        gw.commit()
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
        gw.commit()
        assert count == 0
        result = conn.execute(f"MATCH (t:UIText {{id:'{text.id}'}}) RETURN count(t)")
        assert result.get_next()[0] == 1

    def test_findable_via_list_texts_with_no_owning_component(self, writer):
        gw, conn = writer
        text = TextEntry.create(content="Visão Geral", text_type="label", source="DETAIL_TABS")
        gw.write_module_texts([text])
        gw.commit()
        reader = GraphReader(conn)
        contents = {t["t.content"] for t in reader.list_texts()}
        assert "Visão Geral" in contents


class TestWriteComponent:
    def _make_comp(self, name, child_refs=None):
        return ExtractedComponent(
            name=name, comp_type="card", source_code="<div/>",
            occurrence=1, classes="", styles=[], interactions=[],
            texts=[], child_refs=child_refs or [],
        )

    def test_inserts_component_node(self, writer):
        gw, conn = writer
        gw.write_component(self._make_comp("TestComp"))
        gw.commit()
        result = conn.execute("MATCH (c:Component {name:'TestComp'}) RETURN c.name")
        assert result.get_next()[0] == "TestComp"

    def test_idempotent_on_duplicate(self, writer):
        gw, conn = writer
        gw.write_component(self._make_comp("DupComp"))
        gw.write_component(self._make_comp("DupComp"))
        gw.commit()
        result = conn.execute("MATCH (c:Component {name:'DupComp'}) RETURN count(c)")
        assert result.get_next()[0] == 1

    def test_existing_shell_component_does_not_warn_on_full_component_write(self, writer, caplog):
        gw, conn = writer
        screen = ExtractedScreen(name="ShellFirstPage",
                                 component_refs=["MenuFormModal"], sections_count=0)
        gw.write_screen(screen, [])

        gw.write_component(self._make_comp("MenuFormModal"))

        gw.commit()
        result = conn.execute("MATCH (c:Component {name:'MenuFormModal'}) RETURN count(c)")
        assert result.get_next()[0] == 1
        assert "duplicated primary key value MenuFormModal" not in caplog.text

        resolved = conn.execute(
            "MATCH (c:Component {name:'MenuFormModal'}) "
            "RETURN c.occurrence, c.source_code"
        ).get_next()
        assert resolved == [1, "<div/>"]

    def test_screen_reference_creates_unresolved_component_shell(self, writer):
        gw, conn = writer
        screen = ExtractedScreen(
            name="ShellPage", component_refs=["MissingCard"], sections_count=0
        )

        gw.write_screen(screen, [])

        gw.commit()
        occurrence = conn.execute(
            "MATCH (c:Component {name:'MissingCard'}) RETURN c.occurrence"
        ).get_next()[0]
        assert occurrence == 0

    def test_declared_screen_reference_is_not_created_as_component_shell(self, writer):
        gw, conn = writer
        dashboard = ExtractedScreen("DashboardPage", ["FreeDashboard"], 0)
        free = ExtractedScreen("FreeDashboard", [], 0)
        gw.declare_screens([dashboard, free])

        gw.write_screen(dashboard, [])

        gw.commit()
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
            component_refs=["RestaurantSectorsView"], texts=[], source_code="<div/>",
            detection_method="semantic",
        )
        gw.declare_screens([parent, child])

        gw.write_screen(parent, [section])

        gw.commit()
        links = conn.execute(
            "MATCH (:Section {id:'sectors'})-[:SECTION_USES_SCREEN]->"
            "(:Screen {name:'RestaurantSectorsView'}) RETURN count(*)"
        ).get_next()[0]
        assert links == 1

    def test_creates_contains_relation(self, writer):
        gw, conn = writer
        gw.write_component(self._make_comp("ChildComp"))
        gw.write_component(self._make_comp("ParentComp", child_refs=["ChildComp"]))
        gw.commit()
        result = conn.execute(
            "MATCH (p:Component {name:'ParentComp'})-[:CONTAINS]->(c:Component) "
            "RETURN c.name"
        )
        assert result.get_next()[0] == "ChildComp"

    def test_contains_not_created_for_missing_child(self, writer):
        gw, conn = writer
        gw.write_component(self._make_comp("OrphanParent", child_refs=["Nonexistent"]))
        gw.commit()
        result = conn.execute("MATCH ()-[:CONTAINS]->() RETURN count(*)")
        assert result.get_next()[0] == 0

    def test_style_linked_to_component(self, writer):
        gw, conn = writer
        comp = ExtractedComponent(
            name="StyledComp", comp_type="button", source_code="",
            occurrence=1, classes="",
            styles=[StyleEntry(id="st_sc1", element="StyledComp",
                               state="default", property="color", value="red")],
            interactions=[], texts=[], child_refs=[],
        )
        gw.write_component(comp)
        gw.commit()
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
        comp = ExtractedComponent(
            name="TokenComp", comp_type="button", source_code="",
            occurrence=1, classes="",
            styles=[StyleEntry(id="st_tok1", element="TokenComp",
                               state="default", property="bg", value="#ffb81c")],
            interactions=[], texts=[], child_refs=[],
        )
        gw.write_component(comp)
        gw.commit()
        result = conn.execute(
            "MATCH (c:Component {name:'TokenComp'})-[:USES_TOKEN]->(t:Token) "
            "RETURN t.label"
        )
        assert result.get_next()[0] == "primary"


class TestWriteScreen:
    def test_inserts_screen_node(self, writer):
        gw, conn = writer
        screen = ExtractedScreen(name="TestPage", component_refs=[], sections_count=0)
        gw.write_screen(screen, [])
        gw.commit()
        result = conn.execute("MATCH (s:Screen {name:'TestPage'}) RETURN s.name")
        assert result.get_next()[0] == "TestPage"

    def test_creates_shell_for_unknown_ref(self, writer):
        gw, conn = writer
        screen = ExtractedScreen(name="ShellPage",
                                 component_refs=["UnknownWidget"], sections_count=0)
        gw.write_screen(screen, [])
        gw.commit()
        result = conn.execute(
            "MATCH (c:Component {name:'UnknownWidget'}) RETURN c.source_code"
        )
        assert result.get_next()[0] == ""

    def test_section_linked_to_screen(self, writer):
        gw, conn = writer
        screen = ExtractedScreen(name="SectionPage", component_refs=[], sections_count=1)
        section = ExtractedSection(
            id="sec_t1", screen="SectionPage", name="Header",
            styles={}, component_refs=[], texts=[], source_code="<div/>",
            detection_method="comment",
        )
        gw.write_screen(screen, [section])
        gw.commit()
        result = conn.execute(
            "MATCH (s:Screen {name:'SectionPage'})-[:HAS_SECTION]->(sec:Section) "
            "RETURN sec.name"
        )
        assert result.get_next()[0] == "Header"


class TestGetStats:
    def test_all_keys_present(self, writer):
        gw, _ = writer
        gw.commit()
        stats = gw.get_stats()
        for key in ("screens", "components", "tokens", "contains"):
            assert key in stats

    def test_empty_db_all_zeros(self, writer):
        gw, _ = writer
        gw.commit()
        stats = gw.get_stats()
        assert all(v == 0 for v in stats.values())

    def test_distinguishes_extracted_and_unresolved_components(self, writer):
        gw, _ = writer
        gw.write_component(TestWriteComponent()._make_comp("KnownCard"))
        gw.write_screen(
            ExtractedScreen("ShellPage", ["KnownCard", "MissingCard"], 0), [])

        gw.commit()
        stats = gw.get_stats()

        assert stats["components"] == 2
        assert stats["extracted_components"] == 1
        assert stats["unresolved_components"] == 1


class TestRefusedRows:
    """A row the database refuses at commit is counted; every other row is still written."""

    @staticmethod
    def _component(name: str, occurrence: object = 1) -> ExtractedComponent:
        return ExtractedComponent(name=name, comp_type="component", source_code="", occurrence=occurrence, classes="")

    def test_refused_row_is_counted_and_the_rest_written(self, writer):
        gw, conn = writer
        gw.write_component(self._component("Bad", occurrence="many"))
        gw.write_component(self._component("Good"))
        gw.commit()
        assert len(gw._write_errors) == 1
        assert conn.execute("MATCH (c:Component) RETURN c.name").get_all() == [["Good"]]

    def test_duplicate_primary_key_is_not_counted(self, writer):
        gw, _ = writer
        token = DesignToken(id="dup", category="color", label="A", value="#aaa", usage=1)
        gw.write_tokens([token])
        gw.write_tokens([token])
        gw.commit()
        assert gw._write_errors == []

    def test_get_stats_reports_write_error_count(self, writer):
        gw, _ = writer
        gw.write_component(self._component("Bad1", occurrence="many"))
        gw.write_component(self._component("Bad2", occurrence="few"))
        gw.commit()
        assert gw.get_stats()["write_errors"] == 2

    def test_write_error_tracking_is_capped(self, writer):
        gw, _ = writer
        for n in range(gw._MAX_TRACKED_WRITE_ERRORS + 10):
            gw.write_component(self._component(f"Bad{n}", occurrence="many"))
        gw.commit()
        assert len(gw._write_errors) == gw._MAX_TRACKED_WRITE_ERRORS


class TestCommit:
    def test_nothing_is_written_before_commit(self, writer):
        gw, conn = writer
        gw.write_tokens([DesignToken(id="t", category="color", label="A", value="#aaa", usage=1)])
        assert conn.execute("MATCH (t:Token) RETURN count(t)").get_next()[0] == 0
        gw.commit()
        assert conn.execute("MATCH (t:Token) RETURN count(t)").get_next()[0] == 1

    def test_second_commit_writes_nothing_again(self, writer):
        gw, conn = writer
        gw.write_tokens([DesignToken(id="t", category="color", label="A", value="#aaa", usage=1)])
        gw.commit()
        gw.commit()
        assert conn.execute("MATCH (t:Token) RETURN count(t)").get_next()[0] == 1

    def test_writing_after_commit_is_refused(self, writer):
        gw, _ = writer
        gw.commit()
        with pytest.raises(RuntimeError, match="already committed"):
            gw.write_tokens([DesignToken(id="t", category="color", label="A", value="#aaa", usage=1)])


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


class TestOrderIndex:
    """C30/T63-T65: CONTAINS.order_index preserves sibling render order —
    first-appearance order in the source JSX, not alphabetical."""

    @pytest.fixture()
    def fresh(self, tmp_path):
        db   = kuzu.Database(str(tmp_path / "order.db"))
        conn = kuzu.Connection(db)
        initialize_schema(conn)
        return writer_and_reader(conn)

    def _comp(self, name, child_refs=None):
        return ExtractedComponent(
            name=name, comp_type="card", source_code="<div/>",
            occurrence=1, classes="", styles=[], interactions=[], texts=[],
            child_refs=child_refs or [],
        )

    def test_order_index_persisted_in_declared_order(self, fresh):
        for name in ("Zebra", "Alpha", "Mango"):
            fresh.writer.write_component(self._comp(name))
        fresh.writer.write_component(self._comp("Parent", ["Zebra", "Alpha", "Mango"]))
        fresh.writer.commit()
        rows = fresh.conn.execute(
            "MATCH (p:Component {name:'Parent'})-[r:CONTAINS]->(c:Component) "
            "RETURN c.name, r.order_index ORDER BY r.order_index"
        )
        ordered = []
        while rows.has_next():
            ordered.append(rows.get_next())
        assert [n for n, _ in ordered] == ["Zebra", "Alpha", "Mango"]
        assert [i for _, i in ordered] == [0, 1, 2]

    def test_get_component_children_returns_render_order_not_alphabetical(self, fresh):
        for name in ("Zebra", "Alpha", "Mango"):
            fresh.writer.write_component(self._comp(name))
        fresh.writer.write_component(self._comp("Parent", ["Zebra", "Alpha", "Mango"]))
        assert fresh.reader.get_component_children("Parent") == ["Zebra", "Alpha", "Mango"]

    def test_deferred_contains_edge_keeps_its_order_index(self, fresh):
        # Parent written before its children exist — order_index must
        # survive the deferred/flush_pending_contains path too.
        fresh.writer.write_component(self._comp("Parent", ["Zebra", "Alpha"]))
        fresh.writer.write_component(self._comp("Zebra"))
        fresh.writer.write_component(self._comp("Alpha"))
        fresh.writer.flush_pending_contains()
        assert fresh.reader.get_component_children("Parent") == ["Zebra", "Alpha"]

    def test_screen_full_children_follow_render_order(self, fresh):
        for name in ("Zebra", "Alpha"):
            fresh.writer.write_component(self._comp(name))
        fresh.writer.write_component(self._comp("Parent", ["Zebra", "Alpha"]))
        screen = ExtractedScreen(name="OrderScreen", component_refs=["Parent"], sections_count=0)
        fresh.writer.write_screen(screen, [])
        full = fresh.reader.get_screen_full("OrderScreen")
        parent = next(c for c in full["components"] if c["name"] == "Parent")
        assert parent["children"] == ["Zebra", "Alpha"]


class TestGetBuildDiff:
    """C31/T69: GraphReader reads the persisted last_diff from
    <database>.state.json — no state_path, no file, or a malformed/legacy
    file must all degrade to None, never raise."""

    @pytest.fixture()
    def reader_with_conn(self, tmp_path):
        db   = kuzu.Database(str(tmp_path / "diff.db"))
        conn = kuzu.Connection(db)
        initialize_schema(conn)
        return conn, tmp_path

    def test_none_when_no_state_path_given(self, reader_with_conn):
        conn, _ = reader_with_conn
        reader = GraphReader(conn)
        assert reader.get_build_diff() is None

    def test_none_when_state_file_missing(self, reader_with_conn):
        conn, tmp_path = reader_with_conn
        reader = GraphReader(conn, state_path=tmp_path / "missing.db.state.json")
        assert reader.get_build_diff() is None

    def test_returns_persisted_diff_payload(self, reader_with_conn):
        import json as _json
        conn, tmp_path = reader_with_conn
        state_path = tmp_path / "diff.db.state.json"
        state_path.write_text(_json.dumps({
            "last_diff": {
                "is_first_build": False,
                "screens_added": ["NewPage"],
                "screens_removed": [],
                "comps_added": ["NewBtn"],
                "comps_removed": ["OldBtn"],
            }
        }))
        reader = GraphReader(conn, state_path=state_path)
        diff = reader.get_build_diff()
        assert diff["screens_added"] == ["NewPage"]
        assert diff["comps_removed"] == ["OldBtn"]

    def test_diff_payload_carries_skipped_entries(self, reader_with_conn):
        import json as _json
        conn, tmp_path = reader_with_conn
        state_path = tmp_path / "diff2.db.state.json"
        state_path.write_text(_json.dumps({
            "last_diff": {"is_first_build": True, "screens_added": [], "screens_removed": [],
                           "comps_added": [], "comps_removed": []},
            "skipped_entries": 2,
        }))
        reader = GraphReader(conn, state_path=state_path)
        assert reader.get_build_diff()["skipped_entries"] == 2

    def test_diff_payload_defaults_skipped_entries_to_zero(self, reader_with_conn):
        import json as _json
        conn, tmp_path = reader_with_conn
        state_path = tmp_path / "diff3.db.state.json"
        state_path.write_text(_json.dumps({
            "last_diff": {"is_first_build": True, "screens_added": [], "screens_removed": [],
                           "comps_added": [], "comps_removed": []},
        }))
        reader = GraphReader(conn, state_path=state_path)
        assert reader.get_build_diff()["skipped_entries"] == 0

    def test_none_when_state_file_has_no_diff_key(self, reader_with_conn):
        import json as _json
        conn, tmp_path = reader_with_conn
        state_path = tmp_path / "diff.db.state.json"
        state_path.write_text(_json.dumps({"html_hash": "abc"}))  # legacy shape, no last_diff
        reader = GraphReader(conn, state_path=state_path)
        assert reader.get_build_diff() is None

    def test_none_when_state_file_is_malformed_json(self, reader_with_conn):
        conn, tmp_path = reader_with_conn
        state_path = tmp_path / "diff.db.state.json"
        state_path.write_text("{not valid json")
        reader = GraphReader(conn, state_path=state_path)
        assert reader.get_build_diff() is None


class TestGetComponentFull:
    """C31/T67: one call reconstructs a component's whole subtree, not just
    its direct children — including grandchildren, in render order."""

    @pytest.fixture()
    def fresh(self, tmp_path):
        db   = kuzu.Database(str(tmp_path / "full.db"))
        conn = kuzu.Connection(db)
        initialize_schema(conn)
        return writer_and_reader(conn)

    def _comp(self, name, child_refs=None, styles=None):
        return ExtractedComponent(
            name=name, comp_type="card", source_code=f"<div>{name}</div>",
            occurrence=1, classes="", styles=styles or [],
            interactions=[], texts=[], child_refs=child_refs or [],
        )

    def test_none_when_root_not_found(self, fresh):
        assert fresh.reader.get_component_full("Nonexistent") is None

    def test_includes_root_and_descendants(self, fresh):
        fresh.writer.write_component(self._comp("Grandchild"))
        fresh.writer.write_component(self._comp("Child", ["Grandchild"]))
        fresh.writer.write_component(self._comp("Root", ["Child"]))
        full = fresh.reader.get_component_full("Root")
        names = {c["name"] for c in full["components"]}
        assert names == {"Root", "Child", "Grandchild"}
        assert full["root"] == "Root"

    def test_children_in_render_order(self, fresh):
        for name in ("Zebra", "Alpha"):
            fresh.writer.write_component(self._comp(name))
        fresh.writer.write_component(self._comp("Root", ["Zebra", "Alpha"]))
        full = fresh.reader.get_component_full("Root")
        root = next(c for c in full["components"] if c["name"] == "Root")
        assert root["children"] == ["Zebra", "Alpha"]

    def test_each_component_carries_its_own_styles(self, fresh):
        style = StyleEntry(id="st_x", element="Child", state="default",
                            property="color", value="red")
        fresh.writer.write_component(self._comp("Child", styles=[style]))
        fresh.writer.write_component(self._comp("Root", ["Child"]))
        full = fresh.reader.get_component_full("Root")
        child = next(c for c in full["components"] if c["name"] == "Child")
        assert child["styles_by_state"]["default"] == [{"property": "color", "value": "red"}]

    def test_fuzzy_match_resolves_root(self, fresh):
        fresh.writer.write_component(self._comp("RestaurantCard"))
        full = fresh.reader.get_component_full("Restaurant")
        assert full["root"] == "RestaurantCard"


class TestComponentExists:
    def test_true_for_existing_component(self, populated_db):
        assert populated_db.reader.component_exists("BtnWithBadge") is True

    def test_false_for_leaf_lookalike_that_does_not_exist(self, populated_db):
        assert populated_db.reader.component_exists("TotallyUnknown") is False


class TestFuzzyFastPath:
    """C27/T52: an exact match must short-circuit before the full-scan fuzzy fallback."""

    def test_exact_component_match_skips_full_scan(self, populated_db):
        reader = populated_db.reader
        calls = []
        original = reader._q

        def spy(cypher, params=None):
            calls.append(cypher)
            return original(cypher, params)

        reader._q = spy
        try:
            resolved = reader._fuzzy_find_component("BtnWithBadge")
        finally:
            reader._q = original
        assert resolved == "BtnWithBadge"
        assert len(calls) == 2  # exact Screen and Component checks, no full scan

    def test_prefix_component_match_still_falls_back(self, populated_db):
        reader = populated_db.reader
        calls = []
        original = reader._q

        def spy(cypher, params=None):
            calls.append(cypher)
            return original(cypher, params)

        reader._q = spy
        try:
            resolved = reader._fuzzy_find_component("BtnWithBadg")
        finally:
            reader._q = original
        assert resolved == "BtnWithBadge"
        assert len(calls) == 4  # both exact-match misses, then both full scans

    def test_exact_screen_match_skips_full_scan(self, populated_db):
        reader = populated_db.reader
        calls = []
        original = reader._q

        def spy(cypher, params=None):
            calls.append(cypher)
            return original(cypher, params)

        reader._q = spy
        try:
            resolved = reader._fuzzy_find_screen("RestaurantsPage")
        finally:
            reader._q = original
        assert resolved == "RestaurantsPage"
        assert len(calls) == 2  # exact Screen and Component checks, no full scan


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

    btn = ExtractedComponent(
        name="BtnWithBadge", comp_type="button", source_code="<button/>",
        occurrence=1, classes="", child_refs=[],
        styles=[StyleEntry(id="st_primary", element="BtnWithBadge", state="default",
                           property="backgroundColor", value="#ffb81c")],
        interactions=[], texts=[],
    )
    gw.write_component(btn)

    dark_card = ExtractedComponent(
        name="DarkCard", comp_type="card", source_code="<div/>",
        occurrence=1, classes="", child_refs=[],
        styles=[StyleEntry(id="st_dark", element="DarkCard", state="default",
                           property="backgroundColor", value="#111111")],
        interactions=[], texts=[],
    )
    gw.write_component(dark_card)

    restaurants = ExtractedScreen(name="RestaurantsPage", component_refs=["BtnWithBadge"], sections_count=0)
    orders = ExtractedScreen(name="OrdersPage", component_refs=["DarkCard"], sections_count=0)
    gw.write_screen(restaurants, [])
    gw.write_screen(orders, [])

    gw.commit()
    gw.commit()
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

class TestGetFullSourceFallsBackToScreen:
    """
    get_full_source('ItemEditorV6') failed outright before this: a full-page
    overlay shell is classified as a Screen and (deliberately) never also
    extracted as a Component, so a Component-only lookup always came up
    empty for it. get_full_source must resolve a Screen's own source_code
    when no Component of that name exists — not report the screen's shell
    JSX as "unavailable" when it was captured, just filed differently.
    """

    @pytest.fixture()
    def fresh_writer(self, tmp_path):
        db = kuzu.Database(str(tmp_path / "screen_jsx.db"))
        conn = kuzu.Connection(db)
        initialize_schema(conn)
        return writer_and_reader(conn)

    def test_screen_without_matching_component_returns_its_own_jsx(self, fresh_writer):
        screen = ExtractedScreen(
            name="ItemEditorV6", component_refs=["BasicTab"], sections_count=0,
            source_code="<div className='shell'>{tab === 'basic' && <BasicTab />}</div>",
        )
        fresh_writer.writer.declare_screens([screen])
        result = fresh_writer.reader.get_full_source("ItemEditorV6")["source_code"]
        assert "shell" in result
        assert "BasicTab" in result

    def test_component_of_same_name_still_takes_precedence(self, fresh_writer):
        # A name that resolves to a real Component (the common case) must
        # keep returning the Component's JSX unchanged — the Screen
        # fallback only fires when no Component matches at all.
        comp = ExtractedComponent(
            name="PricingPageV6", comp_type="card", source_code="<div>component version</div>",
            occurrence=1, classes="", styles=[], interactions=[], texts=[], child_refs=[],
        )
        fresh_writer.writer.write_component(comp)
        screen = ExtractedScreen(
            name="PricingPageV6", component_refs=[], sections_count=0,
            source_code="<div>should not surface</div>",
        )
        fresh_writer.writer.declare_screens([screen])
        result = fresh_writer.reader.get_full_source("PricingPageV6")["source_code"]
        assert result == "<div>component version</div>"

    def test_unknown_name_still_returns_empty(self, fresh_writer):
        assert fresh_writer.reader.get_full_source("NoSuchThing") is None


class TestSourceFactsRoundTrip:
    """A stored source keeps the language its capture stated."""

    @pytest.fixture()
    def graph(self, tmp_path):
        db = kuzu.Database(str(tmp_path / "facts.db"))
        conn = kuzu.Connection(db)
        initialize_schema(conn)
        return writer_and_reader(conn)

    def test_component_source_facts_survive_write_and_read(self, graph):
        comp = ExtractedComponent(
            name="CartList", comp_type="component", source_code="<ul>{[list:Item]}</ul>",
            occurrence=1, classes="", source_lang="jsx",
            declares_inline_styles=True,
        )
        graph.writer.write_component(comp)
        full = graph.reader.get_full_source("CartList")
        assert full == {"source_code": "<ul>{[list:Item]}</ul>", "source_lang": "jsx"}
        assert graph.reader.get_component("CartList")["c.declares_inline_styles"] is True

    def test_screen_source_facts_survive_write_and_read(self, graph):
        screen = ExtractedScreen(
            name="Welcome", source_code="<main>{{t}}</main>", source_lang="html-template",
        )
        graph.writer.declare_screens([screen])
        full = graph.reader.get_full_source("Welcome")
        assert full["source_lang"] == "html-template"

    def test_section_keeps_its_source_language(self, graph):
        section = ExtractedSection.create(
            screen="Welcome", name="Header", styles={}, component_refs=[], texts=[],
            source_code="<header>x</header>", detection_method="semantic", source_lang="html",
        )
        graph.writer.write_screen(ExtractedScreen(name="Welcome"), [section])
        assert graph.reader.get_section("Welcome", "Header")["source_lang"] == "html"

    def test_unknown_name_has_no_source(self, graph):
        assert graph.reader.get_full_source("Nothing") is None


class TestTokenModesAndCustomProperties:
    """
    A token can hold one value per mode (light/dark…), and a style that
    references a custom property — `var(--accent)` — uses that token in every
    mode, wherever the reference sits inside the value.
    """

    @pytest.fixture()
    def graph(self, tmp_path):
        db = kuzu.Database(str(tmp_path / "modes.db"))
        conn = kuzu.Connection(db)
        initialize_schema(conn)
        return writer_and_reader(conn)

    @staticmethod
    def _accent(mode: str, value: str) -> DesignToken:
        return DesignToken(id=f"cv_accent_{mode}", category="css_var", label="--accent",
                           value=value, usage=1, mode=mode)

    @staticmethod
    def _styled(name: str, value: str) -> ExtractedComponent:
        return ExtractedComponent(
            name=name, comp_type="component", source_code="<div/>", occurrence=1, classes="",
            styles=[StyleEntry.create(name, "color", value)],
        )

    def _linked_labels(self, graph, name: str) -> list[tuple[str, str]]:
        graph.writer.commit()
        rows = graph.conn.execute(
            "MATCH (c:Component {name:$n})-[:HAS_STYLE]->(:Style)-[:STYLE_USES_TOKEN]->(t:Token) "
            "RETURN t.label, t.mode ORDER BY t.mode", {"n": name},
        )
        out = []
        while rows.has_next():
            out.append(tuple(rows.get_next()))
        return out

    def test_token_mode_survives_write_and_read(self, graph):
        graph.writer.write_tokens([self._accent("escuro", "#5FB0B0")])
        assert graph.reader.get_tokens()[0]["t.mode"] == "escuro"

    def test_token_without_mode_reads_as_empty(self):
        assert DesignToken(id="c1", category="color", label="x", value="#fff", usage=1).mode == ""

    def test_custom_property_reference_uses_the_token_in_every_mode(self, graph):
        graph.writer.write_tokens([self._accent("claro", "#0D5C63"), self._accent("escuro", "#5FB0B0")])
        graph.writer.write_component(self._styled("Cta", "var(--accent)"))
        assert self._linked_labels(graph, "Cta") == [("--accent", "claro"), ("--accent", "escuro")]
        used = graph.conn.execute("MATCH (:Component {name:'Cta'})-[:USES_TOKEN]->(t) RETURN count(t)")
        assert used.get_next()[0] == 2

    def test_component_reads_carry_each_token_mode(self, graph):
        graph.writer.write_tokens([self._accent("claro", "#0D5C63"), self._accent("escuro", "#5FB0B0")])
        graph.writer.write_component(self._styled("Cta", "var(--accent)"))
        for read in (graph.reader.get_component, graph.reader.get_component_spec):
            assert sorted(t["t.mode"] for t in read("Cta")["tokens"]) == ["claro", "escuro"]
        tree = graph.reader.get_component_full("Cta")["components"][0]
        assert sorted(t["mode"] for t in tree["tokens"]) == ["claro", "escuro"]

    def test_reference_inside_a_compound_value_is_found(self, graph):
        graph.writer.write_tokens([self._accent("claro", "#0D5C63")])
        graph.writer.write_component(self._styled("Box", "1px solid var( --accent , #000)"))
        assert self._linked_labels(graph, "Box") == [("--accent", "claro")]

    def test_reference_to_an_unknown_property_links_nothing(self, graph):
        graph.writer.write_tokens([self._accent("claro", "#0D5C63")])
        graph.writer.write_component(self._styled("Ghost", "var(--missing)"))
        assert self._linked_labels(graph, "Ghost") == []


class TestTokenListOrder:
    """Token lists are ordered by category, label and mode — never by the order tokens happened to be stored."""

    @pytest.fixture()
    def reader(self, tmp_path):
        conn = kuzu.Connection(kuzu.Database(str(tmp_path / "order.db")))
        initialize_schema(conn)
        writer = GraphWriter(conn)
        writer.write_tokens([
            DesignToken(id="z_e", category="css_var", label="--zeta", value="#222", usage=1, mode="escuro"),
            DesignToken(id="z_c", category="css_var", label="--zeta", value="#111", usage=1, mode="claro"),
            DesignToken(id="a_c", category="css_var", label="--alfa", value="#333", usage=1, mode="claro"),
        ])
        writer.write_component(ExtractedComponent(
            name="Card", comp_type="component", source_code="", occurrence=1, classes="",
            styles=[StyleEntry.create("Card", "color", "var(--zeta)"), StyleEntry.create("Card", "background", "var(--alfa)")],
        ))
        getattr(writer, "commit", lambda: None)()
        return GraphReader(conn)

    _SORTED = [("--alfa", "claro"), ("--zeta", "claro"), ("--zeta", "escuro")]

    def test_component_tokens(self, reader):
        for read in (reader.get_component, reader.get_component_spec):
            assert [(t["t.label"], t["t.mode"]) for t in read("Card")["tokens"]] == self._SORTED

    def test_component_tree_tokens(self, reader):
        tokens = reader.get_component_full("Card")["components"][0]["tokens"]
        assert [(t["label"], t["mode"]) for t in tokens] == self._SORTED

    def test_all_tokens(self, reader):
        assert [(t["t.label"], t["t.mode"]) for t in reader.get_tokens()] == self._SORTED


class TestTokensByMode:
    """Asking for one mode returns that mode's values plus the tokens every mode shares."""

    @pytest.fixture()
    def reader(self, tmp_path):
        conn = kuzu.Connection(kuzu.Database(str(tmp_path / "bymode.db")))
        initialize_schema(conn)
        writer = GraphWriter(conn)
        writer.write_tokens([
            DesignToken(id="a_c", category="css_var", label="--accent", value="#0D5C63", usage=1, mode="claro"),
            DesignToken(id="a_e", category="css_var", label="--accent", value="#5FB0B0", usage=1, mode="escuro"),
            DesignToken(id="gap", category="spacing", label="space_16", value="16px", usage=4),
        ])
        writer.commit()
        return GraphReader(conn)

    def test_one_mode_keeps_shared_tokens_and_drops_other_modes(self, reader):
        values = {r["t.value"] for r in reader.get_tokens(mode="escuro")}
        assert values == {"#5FB0B0", "16px"}

    def test_no_mode_returns_every_mode(self, reader):
        assert len(reader.get_tokens()) == 3

    def test_mode_combines_with_category(self, reader):
        assert [r["t.value"] for r in reader.get_tokens("css_var", mode="claro")] == ["#0D5C63"]


class TestWholeSourceIsStored:
    def test_long_component_and_screen_sources_are_stored_whole(self, tmp_path):
        conn = kuzu.Connection(kuzu.Database(str(tmp_path / "whole.db")))
        initialize_schema(conn)
        gw = GraphWriter(conn)
        long_source = "<div>" + "x" * 50_000 + "</div>"
        gw.write_component(ExtractedComponent(name="Big", comp_type="component", source_code=long_source,
                                              occurrence=1, classes=""))
        gw.write_screen(ExtractedScreen(name="Page", component_refs=[], sections_count=0, source_code=long_source), [])
        gw.commit()
        reader = GraphReader(conn)
        assert reader.get_full_source("Big")["source_code"] == long_source
        assert reader.get_full_source("Page")["source_code"] == long_source


class TestScreenOwnStyles:
    def test_a_screen_own_styles_are_read_and_shown_in_page_order(self, tmp_path):
        from design_graph.interface.mcp.screen_tools import get_screen_full

        conn = kuzu.Connection(kuzu.Database(str(tmp_path / "screen_styles.db")))
        initialize_schema(conn)
        gw = GraphWriter(conn)
        gw.write_screen(ExtractedScreen(name="Page", component_refs=[], sections_count=0, styles=[
            StyleEntry.create("div", "width", "390px"), StyleEntry.create("div > div", "display", "flex"),
        ]), [])
        gw.commit()
        reader = GraphReader(conn)
        assert reader.get_screen_full("Page")["styles"] == [
            {"element": "div", "property": "width", "value": "390px"},
            {"element": "div > div", "property": "display", "value": "flex"},
        ]
        assert "- **div** `width`: `390px`" in get_screen_full(reader, "Page")
