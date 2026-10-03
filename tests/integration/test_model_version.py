"""
A graph records which model version it was written in and which capture
produced it. Readers refuse a graph from another model version instead of
failing later on a missing column, and a rebuild never skips an outdated one.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import kuzu

from design_graph.interface.mcp.server import _load_readers
from design_graph.model.graph.reader import GraphReader
from design_graph.model.graph.schema import MODEL_VERSION
from design_graph.pipeline.coordinator import run_pipeline

SIMPLE_HTML = Path(__file__).parents[1] / "fixtures" / "simple.html"


def _build(tmp_path: Path) -> tuple[Path, Path]:
    db_path, state_path = tmp_path / "simple.db", tmp_path / "simple.db.state.json"
    asyncio.run(run_pipeline(SIMPLE_HTML, db_path, state_path))
    return db_path, state_path


def _reader(db_path: Path) -> GraphReader:
    return GraphReader(kuzu.Connection(kuzu.Database(str(db_path), read_only=True)))


class TestModelInfo:
    def test_built_graph_records_model_version_and_capture(self, tmp_path):
        db_path, _ = _build(tmp_path)
        assert _reader(db_path).model_info() == {"version": MODEL_VERSION, "capture": "html_prototype"}

    def test_graph_without_model_record_has_no_model_info(self, tmp_path):
        conn = kuzu.Connection(kuzu.Database(str(tmp_path / "legacy.db")))
        conn.execute("CREATE NODE TABLE Screen(name STRING, PRIMARY KEY(name))")
        assert GraphReader(conn).model_info() is None


class TestOutdatedGraphs:
    def test_unchanged_prototype_is_rebuilt_when_its_graph_is_from_another_model(self, tmp_path):
        db_path, state_path = _build(tmp_path)
        state = json.loads(state_path.read_text())
        state["schema_version"] = MODEL_VERSION - 1
        state_path.write_text(json.dumps(state))
        assert asyncio.run(run_pipeline(SIMPLE_HTML, db_path, state_path)) is not None

    def test_unchanged_prototype_on_current_model_is_skipped(self, tmp_path):
        db_path, state_path = _build(tmp_path)
        assert asyncio.run(run_pipeline(SIMPLE_HTML, db_path, state_path)) is None

    def test_mcp_refuses_a_graph_from_another_model_with_a_rebuild_hint(self, tmp_path, capsys):
        conn = kuzu.Connection(kuzu.Database(str(tmp_path / "legacy.db")))
        conn.execute("CREATE NODE TABLE Screen(name STRING, PRIMARY KEY(name))")
        del conn
        assert _load_readers(tmp_path) == []
        err = capsys.readouterr().err
        assert "legacy.db" in err and "--force" in err

    def test_mcp_opens_a_current_graph(self, tmp_path):
        _build(tmp_path)
        assert [name for name, _ in _load_readers(tmp_path)] == ["simple"]


class TestIsCurrentModel:
    def test_current_graph_is_current(self, tmp_path):
        db_path, _ = _build(tmp_path)
        assert _reader(db_path).is_current_model() is True

    def test_graph_without_model_record_is_not_current(self, tmp_path):
        conn = kuzu.Connection(kuzu.Database(str(tmp_path / "legacy.db")))
        conn.execute("CREATE NODE TABLE Screen(name STRING, PRIMARY KEY(name))")
        assert GraphReader(conn).is_current_model() is False
