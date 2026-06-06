"""
Tests for graph/writer.py — GraphWriteSession atomic write context.

Responsibilities under test:
  - Success path: temp DB written, final path receives it, temp is gone
  - Failure path: temp DB cleaned up, pre-existing final DB is preserved
  - Writer returned by __enter__ is functional (can write components)
  - Leftover temp from a previous crashed build is cleaned up before starting
"""

from __future__ import annotations

from pathlib import Path

import kuzu
import pytest

from design_graph.core.models import DesignToken, ExtractedComponent
from design_graph.graph.schema import initialize_schema
from design_graph.graph.writer import GraphWriteSession, GraphWriter


# ── Success path ──────────────────────────────────────────────────────────────

class TestGraphWriteSessionSuccess:
    def test_final_db_exists_after_successful_session(self, tmp_path):
        final = tmp_path / "design.db"
        with GraphWriteSession(final) as writer:
            assert isinstance(writer, GraphWriter)
        assert final.exists()

    def test_temp_db_is_gone_after_successful_session(self, tmp_path):
        final = tmp_path / "design.db"
        temp_name = f".design.db.building"
        with GraphWriteSession(final):
            pass
        assert not (tmp_path / temp_name).exists()

    def test_writer_can_write_tokens_inside_session(self, tmp_path):
        final = tmp_path / "design.db"
        token = DesignToken(id="col_1", category="color",
                            label="primary", value="#ffb81c", usage=1)
        with GraphWriteSession(final) as writer:
            written = writer.write_tokens([token])
        assert written == 1

    def test_writer_can_write_component_inside_session(self, tmp_path):
        final = tmp_path / "design.db"
        comp = ExtractedComponent(
            name="TestBtn", comp_type="button",
            jsx_snippet="<button>OK</button>",
            occurrence=1, classes="btn",
            styles=[], interactions=[], texts=[], child_refs=[],
        )
        with GraphWriteSession(final) as writer:
            writer.write_component(comp, {})
        # Verify component is readable after session closes
        db = kuzu.Database(str(final), read_only=True)
        conn = kuzu.Connection(db)
        result = conn.execute("MATCH (c:Component {name:'TestBtn'}) RETURN c.name")
        assert result.has_next()
        conn.close()
        db.close()

    def test_replaces_existing_final_db_on_success(self, tmp_path):
        final = tmp_path / "design.db"
        # First session: write token A
        token_a = DesignToken(id="a", category="color", label="A", value="#aaa", usage=1)
        with GraphWriteSession(final) as writer:
            writer.write_tokens([token_a])
        # Second session: write token B (different DB, no token A)
        token_b = DesignToken(id="b", category="color", label="B", value="#bbb", usage=1)
        with GraphWriteSession(final) as writer:
            writer.write_tokens([token_b])
        # Only token B should exist
        db = kuzu.Database(str(final), read_only=True)
        conn = kuzu.Connection(db)
        result = conn.execute("MATCH (t:Token) RETURN count(t)")
        count = result.get_next()[0]
        conn.close()
        db.close()
        assert count == 1


# ── Failure path ──────────────────────────────────────────────────────────────

class TestGraphWriteSessionFailure:
    def test_temp_db_cleaned_up_on_exception(self, tmp_path):
        final = tmp_path / "design.db"
        temp = tmp_path / ".design.db.building"
        with pytest.raises(ValueError):
            with GraphWriteSession(final):
                raise ValueError("intentional failure")
        assert not temp.exists()

    def test_pre_existing_final_db_preserved_on_failure(self, tmp_path):
        final = tmp_path / "design.db"
        token = DesignToken(id="safe", category="color", label="safe", value="#fff", usage=1)
        # Build a valid DB first
        with GraphWriteSession(final) as writer:
            writer.write_tokens([token])
        assert final.exists()
        # Second build fails — original DB must survive
        with pytest.raises(RuntimeError):
            with GraphWriteSession(final):
                raise RuntimeError("build crashed")
        assert final.exists()

    def test_exception_is_propagated_to_caller(self, tmp_path):
        final = tmp_path / "design.db"
        with pytest.raises(ValueError, match="propagated"):
            with GraphWriteSession(final):
                raise ValueError("propagated")

    def test_no_final_db_created_on_failure(self, tmp_path):
        final = tmp_path / "fresh.db"
        with pytest.raises(RuntimeError):
            with GraphWriteSession(final):
                raise RuntimeError("crash before write")
        assert not final.exists()


# ── Leftover temp cleanup ─────────────────────────────────────────────────────

class TestGraphWriteSessionTempCleanup:
    def test_leftover_temp_from_previous_crash_is_removed_before_start(self, tmp_path):
        """A stale temp dir from a previous crash must be removed before the new session begins."""
        final = tmp_path / "design.db"
        stale_temp = tmp_path / ".design.db.building"
        stale_temp.mkdir()
        (stale_temp / "stale.col").write_bytes(b"stale")

        with GraphWriteSession(final):
            pass  # should succeed despite stale temp existing

        assert final.exists()
        assert not stale_temp.exists()

    def test_parent_directory_created_when_missing(self, tmp_path):
        nested_final = tmp_path / "nested" / "deep" / "design.db"
        with GraphWriteSession(nested_final):
            pass
        assert nested_final.exists()
