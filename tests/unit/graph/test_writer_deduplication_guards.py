"""
Tests for GraphWriter deduplication guards and idempotency paths.

Targets:
  - inserted_names property (line 45)
  - Duplicate style insertion skipped (line 86)
  - Duplicate interaction insertion skipped (line 111)
  - Duplicate text insertion skipped (line 128)
  - Duplicate CONTAINS key skipped (line 147)
  - _safe_execute returns False on Kuzu error (lines 215-217)
"""

from __future__ import annotations

import kuzu
import pytest

from design_graph.core.models import (
    DesignToken,
    ExtractedComponent,
    InteractionEntry,
    StyleEntry,
    TextEntry,
)
from design_graph.graph.schema import initialize_schema
from design_graph.graph.writer import GraphWriter


@pytest.fixture
def writer(tmp_path):
    db   = kuzu.Database(str(tmp_path / "wr.db"))
    conn = kuzu.Connection(db)
    initialize_schema(conn)
    return GraphWriter(conn), conn


def _comp(name: str, **kwargs) -> ExtractedComponent:
    defaults = dict(
        comp_type="card", jsx_snippet="<div/>", occurrence=1,
        classes="", styles=[], interactions=[], texts=[], child_refs=[],
    )
    return ExtractedComponent(name=name, **{**defaults, **kwargs})


def _style(sid: str, comp: str) -> StyleEntry:
    return StyleEntry(id=sid, element=comp, state="default",
                      property="color", value="#fff")


def _interaction(iid: str) -> InteractionEntry:
    return InteractionEntry(id=iid, trigger="hover", css_prop="opacity",
                            from_val="1", to_val="0.8", transition="all 0.2s")


def _text(tid: str, comp: str) -> TextEntry:
    return TextEntry(id=tid, content="Label", text_type="label",
                     source=comp, element="span")


# ── inserted_names property ───────────────────────────────────────────────────

class TestInsertedNamesProperty:
    def test_returns_frozenset(self, writer):
        gw, _ = writer
        assert isinstance(gw.inserted_names, frozenset)

    def test_contains_written_component(self, writer):
        gw, _ = writer
        gw.write_component(_comp("BtnPrimary"), {})
        assert "BtnPrimary" in gw.inserted_names

    def test_is_read_only_snapshot(self, writer):
        gw, _ = writer
        gw.write_component(_comp("Card"), {})
        snapshot = gw.inserted_names
        gw.write_component(_comp("Badge"), {})
        assert "Badge" not in snapshot  # snapshot is immutable


# ── Duplicate style deduplication ────────────────────────────────────────────

class TestDuplicateStyleGuard:
    def test_duplicate_style_id_inserted_only_once(self, writer):
        gw, conn = writer
        style = _style("st_dup", "BtnX")
        comp_with_dup_styles = _comp("BtnX", styles=[style, style])  # same id twice
        gw.write_component(comp_with_dup_styles, {})

        result = conn.execute("MATCH (s:Style {id:'st_dup'}) RETURN count(s)")
        assert result.get_next()[0] == 1


# ── Duplicate interaction deduplication ──────────────────────────────────────

class TestDuplicateInteractionGuard:
    def test_duplicate_interaction_id_inserted_only_once(self, writer):
        gw, conn = writer
        inter = _interaction("int_dup")
        comp_with_dup = _comp("BtnY", interactions=[inter, inter])
        gw.write_component(comp_with_dup, {})

        result = conn.execute("MATCH (i:Interaction {id:'int_dup'}) RETURN count(i)")
        assert result.get_next()[0] == 1


# ── Duplicate UIText deduplication ───────────────────────────────────────────

class TestDuplicateTextGuard:
    def test_duplicate_text_id_inserted_only_once(self, writer):
        gw, conn = writer
        text = _text("tx_dup", "BtnZ")
        comp_with_dup = _comp("BtnZ", texts=[text, text])
        gw.write_component(comp_with_dup, {})

        result = conn.execute("MATCH (t:UIText {id:'tx_dup'}) RETURN count(t)")
        assert result.get_next()[0] == 1


# ── Duplicate CONTAINS key deduplication ─────────────────────────────────────

class TestDuplicateContainsGuard:
    def test_contains_inserted_only_once_for_duplicate_child_refs(self, writer):
        gw, conn = writer
        leaf = _comp("Badge")
        gw.write_component(leaf, {})

        # Parent references Badge twice in child_refs
        parent = _comp("BtnWithBadge", child_refs=["Badge", "Badge"])
        gw.write_component(parent, {})

        result = conn.execute(
            "MATCH (:Component {name:'BtnWithBadge'})-[r:CONTAINS]->(:Component {name:'Badge'}) "
            "RETURN count(r)"
        )
        assert result.get_next()[0] == 1

    def test_contains_edge_created_even_when_parent_written_before_child(self, writer):
        """
        Regression: when parent is inserted before child (occurrence-order),
        the CONTAINS edge must still be created after a flush pass.
        Before the fix, parent-first write silently dropped the edge.
        """
        gw, conn = writer

        # Write PARENT first — child doesn't exist yet
        parent = _comp("Container", child_refs=["InnerWidget"])
        gw.write_component(parent, {})

        # Write CHILD after parent
        child = _comp("InnerWidget")
        gw.write_component(child, {})

        # Flush pending CONTAINS edges (child now exists)
        gw.flush_pending_contains()

        result = conn.execute(
            "MATCH (:Component {name:'Container'})-[r:CONTAINS]->(:Component {name:'InnerWidget'}) "
            "RETURN count(r)"
        )
        assert result.get_next()[0] == 1

    def test_flush_pending_contains_is_idempotent(self, writer):
        gw, conn = writer
        parent = _comp("Wrapper", child_refs=["Leaf"])
        child  = _comp("Leaf")
        gw.write_component(child, {})
        gw.write_component(parent, {})

        gw.flush_pending_contains()
        gw.flush_pending_contains()  # second call must not duplicate edges

        result = conn.execute(
            "MATCH (:Component {name:'Wrapper'})-[r:CONTAINS]->(:Component {name:'Leaf'}) "
            "RETURN count(r)"
        )
        assert result.get_next()[0] == 1


# ── _safe_execute error handling ──────────────────────────────────────────────

class TestSafeExecuteErrorHandling:
    def test_returns_false_on_invalid_cypher(self, writer):
        gw, _ = writer
        result = gw._safe_execute("NOT VALID CYPHER !!!")
        assert result is False

    def test_does_not_raise_on_invalid_cypher(self, writer):
        gw, _ = writer
        gw._safe_execute("INVALID SYNTAX {{{{{{")  # must not raise

    def test_returns_true_on_successful_execute(self, writer):
        gw, _ = writer
        gw.write_component(_comp("TestComp"), {})
        result = gw._safe_execute(
            "MATCH (c:Component {name:'TestComp'}) RETURN c.name"
        )
        assert result is True
