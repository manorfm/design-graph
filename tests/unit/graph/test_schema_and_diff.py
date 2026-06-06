"""Tests for graph/schema.py and graph/diff.py — T09 and T12."""

from collections import Counter

import kuzu
import pytest

from design_graph.core.models import BuildState, ExtractedScreen
from design_graph.graph.diff import compute_diff, compute_screen_hash
from design_graph.graph.schema import STATS_QUERIES, initialize_schema


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def fresh_conn(tmp_path):
    db = kuzu.Database(str(tmp_path / "test.db"))
    return kuzu.Connection(db)


# ── Schema tests ──────────────────────────────────────────────────────────────

class TestInitializeSchema:
    def test_creates_all_node_tables(self, fresh_conn):
        initialize_schema(fresh_conn)
        for table in ["Screen", "Component", "Token", "UIText", "Style", "Interaction", "Section"]:
            fresh_conn.execute(f"MATCH (n:{table}) RETURN count(n)")

    def test_creates_all_rel_tables(self, fresh_conn):
        initialize_schema(fresh_conn)
        for rel in [
            "USES_COMPONENT", "HAS_SECTION", "SECTION_USES", "HAS_STYLE",
            "USES_TOKEN", "COMP_HAS_TEXT", "HAS_INTERACTION", "CONTAINS",
            "STYLE_USES_TOKEN",
        ]:
            fresh_conn.execute(f"MATCH ()-[r:{rel}]->() RETURN count(r)")

    def test_style_uses_token_in_schema_ddl(self):
        from design_graph.graph.schema import SCHEMA
        assert any("STYLE_USES_TOKEN" in stmt for stmt in SCHEMA), (
            "STYLE_USES_TOKEN rel table missing from schema DDL. "
            "Add: CREATE REL TABLE STYLE_USES_TOKEN(FROM Style TO Token)"
        )

    def test_screen_has_text_removed_from_schema_ddl(self):
        from design_graph.graph.schema import SCHEMA
        assert not any("SCREEN_HAS_TEXT" in stmt for stmt in SCHEMA), (
            "SCREEN_HAS_TEXT is dead code (never written by GraphWriter). "
            "Remove it from schema DDL."
        )

    def test_contains_table_stores_weight_property(self, fresh_conn):
        initialize_schema(fresh_conn)
        for name in ("Parent", "Child"):
            fresh_conn.execute(
                "CREATE (:Component {name:$n, comp_type:'card', "
                "jsx_snippet:'', occurrence:1, classes:''})",
                {"n": name}
            )
        fresh_conn.execute(
            "MATCH (p:Component {name:'Parent'}),(c:Component {name:'Child'}) "
            "CREATE (p)-[:CONTAINS {weight:3}]->(c)"
        )
        result = fresh_conn.execute("MATCH ()-[r:CONTAINS]->() RETURN r.weight")
        assert result.get_next()[0] == 3

    def test_section_stores_detection_method(self, fresh_conn):
        initialize_schema(fresh_conn)
        fresh_conn.execute(
            "CREATE (:Section {id:'s1', screen:'Pg', name:'Header', "
            "styles_json:'{}', components_json:'[]', texts_json:'[]', "
            "jsx_snippet:'', detection_method:'comment'})"
        )
        result = fresh_conn.execute(
            "MATCH (s:Section {id:'s1'}) RETURN s.detection_method"
        )
        assert result.get_next()[0] == "comment"

    def test_idempotent_on_double_call(self, fresh_conn):
        initialize_schema(fresh_conn)
        initialize_schema(fresh_conn)  # must not raise


class TestStatsQueries:
    EXPECTED_KEYS = {"screens", "components", "tokens", "texts", "styles", "sections", "interactions", "contains"}

    def test_all_expected_keys_present(self):
        assert self.EXPECTED_KEYS.issubset(STATS_QUERIES.keys())

    def test_all_queries_return_zero_on_empty_db(self, fresh_conn):
        initialize_schema(fresh_conn)
        for _name, cypher in STATS_QUERIES.items():
            result = fresh_conn.execute(cypher)
            assert result.get_next()[0] == 0


# ── Diff tests ────────────────────────────────────────────────────────────────

def _empty_state() -> BuildState:
    return BuildState(html_hash="", last_build="", screens={}, components={})


def _prev_state(**kwargs) -> BuildState:
    return BuildState(
        html_hash=kwargs.get("html_hash", "abc"),
        last_build="",
        screens=kwargs.get("screens", {}),
        components=kwargs.get("components", {}),
    )


def _screen(name: str, refs: list[str] | None = None) -> ExtractedScreen:
    return ExtractedScreen(name=name, component_refs=refs or [], sections_count=0)


class TestComputeDiff:
    def test_first_build_when_no_hash(self):
        diff = compute_diff(_empty_state(), [], Counter())
        assert diff.is_first_build is True

    def test_not_first_build_when_hash_present(self):
        diff = compute_diff(_prev_state(), [], Counter())
        assert diff.is_first_build is False

    def test_screens_added(self):
        prev = _prev_state(screens={"A": "x"})
        diff = compute_diff(prev, [_screen("A"), _screen("B")], Counter())
        assert "B" in diff.screens_added
        assert "A" not in diff.screens_added

    def test_screens_removed(self):
        prev = _prev_state(screens={"A": "x", "B": "y"})
        diff = compute_diff(prev, [_screen("A")], Counter())
        assert "B" in diff.screens_removed

    def test_comps_added(self):
        prev = _prev_state(components={"Btn": 2})
        diff = compute_diff(prev, [], Counter({"Btn": 2, "NewCard": 1}))
        assert "NewCard" in diff.comps_added

    def test_comps_removed(self):
        prev = _prev_state(components={"OldComp": 1, "Btn": 2})
        diff = compute_diff(prev, [], Counter({"Btn": 2}))
        assert "OldComp" in diff.comps_removed


class TestComputeScreenHash:
    def test_same_input_same_hash(self):
        s = _screen("A", ["Btn", "Card"])
        assert compute_screen_hash(s) == compute_screen_hash(s)

    def test_different_refs_different_hash(self):
        a = _screen("A", ["Btn"])
        b = _screen("A", ["Modal"])
        assert compute_screen_hash(a) != compute_screen_hash(b)

    def test_result_is_12_char_hex(self):
        h = compute_screen_hash(_screen("A"))
        assert len(h) == 12
        int(h, 16)
