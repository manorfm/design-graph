"""
Rows → Kuzu: writes a whole build's collected rows one table at a time.

Each table is written with a single `UNWIND $rows` statement per batch of
rows instead of one statement per row — a build's thousands of statements
cost seconds each in parse/plan overhead; a handful of batches cost
milliseconds (docs/changes/C44, T121). Nodes are written before
relationships, so every relationship finds its endpoints; one whose
endpoint does not exist matches nothing and is dropped, as before.

Kuzu rolls a failing statement back whole, so a failing batch is rewritten
row by row: the bad row is reported and every other row still lands.

Table and column names are interpolated into the statements, so only names
the schema declares are accepted; values always travel as parameters.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

from design_graph.model.graph.schema import node_tables, rel_tables

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 500
_SOURCE, _TARGET = "source_key", "target_key"


class _Connection(Protocol):
    def execute(self, query: str, parameters: dict) -> object: ...


@dataclass
class GraphRows:
    """A build's rows, by table, in the order they were collected."""

    nodes: dict[str, dict[str, dict]] = field(default_factory=dict)
    rels: dict[str, list[dict]] = field(default_factory=dict)

    def put_node(self, table: str, key: str, row: dict) -> None:
        """Add a node row; a later row with the same key is ignored, as a repeated CREATE would be."""
        _check_columns(node_tables()[table].columns, row)
        self.nodes.setdefault(table, {}).setdefault(key, row)

    def replace_node(self, table: str, key: str, row: dict) -> None:
        """Add a node row, overwriting any earlier row with the same key in its original place."""
        _check_columns(node_tables()[table].columns, row)
        self.nodes.setdefault(table, {})[key] = row

    def add_rel(self, table: str, source_key: str, target_key: str, **properties: object) -> None:
        _check_columns(rel_tables()[table].columns, properties)
        self.rels.setdefault(table, []).append({_SOURCE: source_key, _TARGET: target_key, **properties})

    def __bool__(self) -> bool:
        return bool(self.nodes or self.rels)


def _check_columns(declared: dict[str, str], row: dict) -> None:
    """Every row carries exactly its table's columns, so one statement fits all of them."""
    if set(row) != set(declared):
        raise KeyError(f"columns {sorted(row)} differ from the schema's {sorted(declared)}")


def write_rows(conn: _Connection, rows: GraphRows, batch_size: int = DEFAULT_BATCH_SIZE) -> list[str]:
    """Write every row, nodes first; returns one message per row that could not be written."""
    errors: list[str] = []
    for table, by_key in rows.nodes.items():
        errors += _write_table(conn, table, _node_statement(table), list(by_key.values()), batch_size)
    for table, rel_rows in rows.rels.items():
        errors += _write_table(conn, table, _rel_statement(table), rel_rows, batch_size)
    return errors


def _typed(column: str, column_type: str) -> str:
    # A column holding only nulls in a batch is inferred as STRING; the cast keeps its declared type.
    return f"r.{column}" if column_type == "STRING" else f"CAST(r.{column} AS {column_type})"


def _node_statement(table: str) -> str:
    values = ", ".join(f"{column}: {_typed(column, kind)}" for column, kind in node_tables()[table].columns.items())
    return f"UNWIND $rows AS r CREATE (:{table} {{{values}}})"


def _rel_statement(table: str) -> str:
    rel = rel_tables()[table]
    source_key, target_key = node_tables()[rel.source].key, node_tables()[rel.target].key
    properties = ", ".join(f"{column}: {_typed(column, kind)}" for column, kind in rel.columns.items())
    return (
        f"UNWIND $rows AS r "
        f"MATCH (a:{rel.source} {{{source_key}: r.{_SOURCE}}}), (b:{rel.target} {{{target_key}: r.{_TARGET}}}) "
        f"CREATE (a)-[:{table}{f' {{{properties}}}' if properties else ''}]->(b)"
    )


def _write_table(conn: _Connection, table: str, statement: str, rows: list[dict], batch_size: int) -> list[str]:
    errors: list[str] = []
    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        if _execute(conn, statement, batch) is not None:
            errors += [error for row in batch if (error := _write_row(conn, table, statement, row))]
    logger.debug("batch: wrote %s (%d rows, %d failed)", table, len(rows), len(errors))
    return errors


def _write_row(conn: _Connection, table: str, statement: str, row: dict) -> str | None:
    exc = _execute(conn, statement, [row])
    if exc is None or "duplicated primary key" in str(exc).lower():
        return None
    logger.warning("batch: skipped a %s row (%s): %r", table, type(exc).__name__, exc)
    return f"{table}: {type(exc).__name__}: {exc}"


def _execute(conn: _Connection, statement: str, rows: list[dict]) -> Exception | None:
    try:
        conn.execute(statement, {"rows": rows})
    except Exception as exc:  # noqa: BLE001 — Kuzu raises plain RuntimeError for every failure
        return exc
    return None
