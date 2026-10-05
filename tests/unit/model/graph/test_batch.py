"""
Writing collected rows to Kuzu in batches: one statement per table (per
batch of rows), nodes before relationships, and a failing batch rewritten
row by row so the one bad row is reported and every other row still lands.
"""

import kuzu
import pytest

from design_graph.model.graph.batch import GraphRows, write_rows
from design_graph.model.graph.schema import initialize_schema, node_tables, rel_tables


class _CountingConnection:
    """A Kuzu connection that counts the statements it runs."""

    def __init__(self, conn):
        self._conn, self.statements = conn, 0

    def execute(self, *args, **kwargs):
        self.statements += 1
        return self._conn.execute(*args, **kwargs)


@pytest.fixture()
def conn(tmp_path):
    connection = kuzu.Connection(kuzu.Database(str(tmp_path / "batch.db")))
    initialize_schema(connection)
    return connection


def _component(name, occurrence=1):
    return {"name": name, "comp_type": "component", "source_code": "", "source_lang": "",
            "source_simplified": False, "declares_inline_styles": False, "occurrence": occurrence,
            "classes": "", "truncated_fields": "", "referenced_data_json": ""}


def _style(style_id):
    return {"id": style_id, "element": "Card", "state": "default", "property": "color",
            "value": "red 'quoted', with\nnewline", "media": ""}


def _all(conn, query):
    return conn.execute(query).get_all()


class TestSchemaTables:
    def test_node_tables_know_their_key_and_column_types(self):
        component = node_tables()["Component"]
        assert component.key == "name"
        assert component.columns["occurrence"] == "INT64"
        assert component.columns["source_simplified"] == "BOOLEAN"

    def test_rel_tables_know_their_endpoints_and_properties(self):
        contains = rel_tables()["CONTAINS"]
        assert (contains.source, contains.target) == ("Component", "Component")
        assert contains.columns == {"weight": "INT64", "order_index": "INT64"}
        assert rel_tables()["HAS_STYLE"].columns == {}


class TestWriteRows:
    def test_nodes_and_relationships_are_written(self, conn):
        rows = GraphRows()
        rows.put_node("Component", "Card", _component("Card"))
        rows.put_node("Style", "s1", _style("s1"))
        rows.add_rel("HAS_STYLE", "Card", "s1")
        rows.add_rel("CONTAINS", "Card", "Card", weight=1, order_index=0)
        assert write_rows(conn, rows) == []
        assert _all(conn, "MATCH (:Component {name:'Card'})-[:HAS_STYLE]->(s:Style) RETURN s.value") == [
            ["red 'quoted', with\nnewline"]
        ]
        assert _all(conn, "MATCH ()-[r:CONTAINS]->() RETURN r.weight, r.order_index") == [[1, 0]]

    def test_one_statement_per_table(self, conn):
        rows = GraphRows()
        for n in range(30):
            rows.put_node("Component", f"C{n}", _component(f"C{n}"))
            rows.put_node("Style", f"s{n}", _style(f"s{n}"))
            rows.add_rel("HAS_STYLE", f"C{n}", f"s{n}")
        counting = _CountingConnection(conn)
        write_rows(counting, rows)
        assert counting.statements == 3

    def test_large_tables_are_split_into_batches(self, conn):
        rows = GraphRows()
        for n in range(5):
            rows.put_node("Component", f"C{n}", _component(f"C{n}"))
        counting = _CountingConnection(conn)
        write_rows(counting, rows, batch_size=2)
        assert counting.statements == 3
        assert _all(conn, "MATCH (c:Component) RETURN count(c)") == [[5]]

    def test_a_later_put_of_the_same_key_is_ignored(self, conn):
        rows = GraphRows()
        rows.put_node("Component", "Card", _component("Card", occurrence=1))
        rows.put_node("Component", "Card", _component("Card", occurrence=3))
        write_rows(conn, rows)
        assert _all(conn, "MATCH (c:Component) RETURN c.occurrence") == [[1]]

    def test_replace_overwrites_the_row_and_keeps_its_place(self, conn):
        rows = GraphRows()
        rows.put_node("Component", "Shell", _component("Shell", occurrence=-1))
        rows.put_node("Component", "Other", _component("Other"))
        rows.replace_node("Component", "Shell", _component("Shell", occurrence=3))
        write_rows(conn, rows)
        assert _all(conn, "MATCH (c:Component) RETURN c.name, c.occurrence") == [["Shell", 3], ["Other", 1]]

    def test_typed_columns_accept_missing_values(self, conn):
        rows = GraphRows()
        rows.put_node("Component", "Card", {**_component("Card"), "occurrence": None})
        assert write_rows(conn, rows) == []
        assert _all(conn, "MATCH (c:Component) RETURN c.occurrence") == [[None]]

    def test_bad_row_is_reported_and_every_other_row_is_written(self, conn):
        rows = GraphRows()
        for name in ("A", "B", "C"):
            rows.put_node("Component", name, _component(name, occurrence="many" if name == "B" else 1))
        errors = write_rows(conn, rows)
        assert len(errors) == 1 and "Component" in errors[0]
        assert _all(conn, "MATCH (c:Component) RETURN c.name ORDER BY c.name") == [["A"], ["C"]]

    def test_relationship_to_a_missing_node_is_dropped_silently(self, conn):
        rows = GraphRows()
        rows.put_node("Component", "Card", _component("Card"))
        rows.add_rel("HAS_STYLE", "Card", "nowhere")
        assert write_rows(conn, rows) == []
        assert _all(conn, "MATCH ()-[r:HAS_STYLE]->() RETURN count(r)") == [[0]]

    def test_row_already_in_the_graph_is_skipped_without_error(self, conn):
        conn.execute("CREATE (:Style {id:'s1', element:'', state:'', property:'', value:'', media:''})")
        rows = GraphRows()
        rows.put_node("Style", "s1", _style("s1"))
        rows.put_node("Style", "s2", _style("s2"))
        assert write_rows(conn, rows) == []
        assert _all(conn, "MATCH (s:Style) RETURN count(s)") == [[2]]

    def test_unknown_table_is_refused(self, conn):
        rows = GraphRows()
        with pytest.raises(KeyError):
            rows.put_node("Nope) DETACH DELETE (n", "x", {"id": "x"})
        with pytest.raises(KeyError):
            rows.add_rel("NOPE", "a", "b")

    def test_column_outside_the_schema_is_refused(self, conn):
        rows = GraphRows()
        with pytest.raises(KeyError):
            rows.put_node("Component", "x", {**_component("x"), "name}) DETACH DELETE (n": 1})
        with pytest.raises(KeyError):
            rows.add_rel("CONTAINS", "a", "b", **{"weight}]->() //": 1})
