"""Integration tests for the full build pipeline — T13."""

import asyncio
from pathlib import Path

import kuzu
import pytest

from design_graph.pipeline.state import load_build_state
from design_graph.pipeline.coordinator import run_pipeline

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"
SIMPLE_HTML = FIXTURE_DIR / "simple.html"


class TestRunPipeline:
    def test_creates_db_file(self, tmp_path):
        db_path = tmp_path / "out.db"
        state_path = tmp_path / ".state.json"
        stats = asyncio.run(run_pipeline(SIMPLE_HTML, db_path, state_path))
        assert db_path.exists()
        assert stats is not None

    def test_skips_unchanged_prototype(self, tmp_path):
        db_path = tmp_path / "out.db"
        state_path = tmp_path / ".state.json"
        asyncio.run(run_pipeline(SIMPLE_HTML, db_path, state_path))
        result = asyncio.run(run_pipeline(SIMPLE_HTML, db_path, state_path))
        assert result is None  # skipped

    def test_force_rebuilds_unchanged(self, tmp_path):
        db_path = tmp_path / "out.db"
        state_path = tmp_path / ".state.json"
        asyncio.run(run_pipeline(SIMPLE_HTML, db_path, state_path))
        result = asyncio.run(run_pipeline(SIMPLE_HTML, db_path, state_path, force=True))
        assert result is not None

    def test_stats_have_positive_duration(self, tmp_path):
        stats = asyncio.run(run_pipeline(
            SIMPLE_HTML, tmp_path / "out.db", tmp_path / ".state.json"
        ))
        assert stats.duration_seconds > 0

    def test_state_file_saved_after_build(self, tmp_path):
        state_path = tmp_path / ".state.json"
        asyncio.run(run_pipeline(SIMPLE_HTML, tmp_path / "out.db", state_path))
        state = load_build_state(state_path)
        assert state.html_hash != ""

    def test_db_has_at_least_one_screen(self, tmp_path):
        db_path = tmp_path / "out.db"
        asyncio.run(run_pipeline(SIMPLE_HTML, db_path, tmp_path / ".state.json"))
        db = kuzu.Database(str(db_path), read_only=True)
        conn = kuzu.Connection(db)
        result = conn.execute("MATCH (s:Screen) RETURN count(s)")
        assert result.get_next()[0] >= 1

    def test_db_has_at_least_one_component(self, tmp_path):
        db_path = tmp_path / "out.db"
        asyncio.run(run_pipeline(SIMPLE_HTML, db_path, tmp_path / ".state.json"))
        db = kuzu.Database(str(db_path), read_only=True)
        conn = kuzu.Connection(db)
        result = conn.execute("MATCH (c:Component) RETURN count(c)")
        assert result.get_next()[0] >= 1

    def test_db_has_at_least_one_token(self, tmp_path):
        db_path = tmp_path / "out.db"
        asyncio.run(run_pipeline(SIMPLE_HTML, db_path, tmp_path / ".state.json"))
        db = kuzu.Database(str(db_path), read_only=True)
        conn = kuzu.Connection(db)
        result = conn.execute("MATCH (t:Token) RETURN count(t)")
        assert result.get_next()[0] >= 1

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            asyncio.run(run_pipeline(
                tmp_path / "ghost.html", tmp_path / "out.db", tmp_path / ".state.json"
            ))

    def test_new_pipeline_finds_same_or_more_screens_than_legacy(self, tmp_path):
        """New pipeline must not lose screens that legacy build_graph found."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))
        try:
            from build_graph import build as legacy_build
        except ImportError:
            pytest.skip("legacy build_graph not available")

        legacy_db = tmp_path / "legacy.db"
        legacy_build(SIMPLE_HTML, legacy_db)
        legacy_kuzu = kuzu.Database(str(legacy_db), read_only=True)
        legacy_conn = kuzu.Connection(legacy_kuzu)
        legacy_screens: set[str] = set()
        r = legacy_conn.execute("MATCH (s:Screen) RETURN s.name")
        while r.has_next():
            legacy_screens.add(r.get_next()[0])

        new_db = tmp_path / "new.db"
        asyncio.run(run_pipeline(SIMPLE_HTML, new_db, tmp_path / ".state.json"))
        new_kuzu = kuzu.Database(str(new_db), read_only=True)
        new_conn = kuzu.Connection(new_kuzu)
        new_screens: set[str] = set()
        r = new_conn.execute("MATCH (s:Screen) RETURN s.name")
        while r.has_next():
            new_screens.add(r.get_next()[0])

        assert legacy_screens.issubset(new_screens), (
            f"Legacy found screens not in new pipeline: "
            f"{legacy_screens - new_screens}"
        )
