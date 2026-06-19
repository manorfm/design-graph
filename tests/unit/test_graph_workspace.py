import json
from pathlib import Path

import pytest

from design_graph.core.graph_catalog import AmbiguousGraphSelection, GraphSelectionSource
from design_graph.workspace import GraphWorkspace


def _db(root: Path, name: str) -> Path:
    path = root / f"{name}.db"
    path.mkdir()
    return path


def test_workspace_refuses_silent_selection_with_multiple_databases(tmp_path, monkeypatch):
    _db(tmp_path, "one")
    _db(tmp_path, "two")
    monkeypatch.setenv("GRAPH_DIR", str(tmp_path))
    monkeypatch.delenv("DESIGN_GRAPH_DOC", raising=False)
    with pytest.raises(AmbiguousGraphSelection):
        GraphWorkspace.open().select()


def test_workspace_uses_environment_before_config(tmp_path, monkeypatch):
    _db(tmp_path, "env")
    _db(tmp_path, "configured")
    config = tmp_path / "design-graph"
    config.mkdir()
    (config / "config.json").write_text(json.dumps({"default_doc": "configured"}))
    monkeypatch.setenv("GRAPH_DIR", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("DESIGN_GRAPH_DOC", "env")
    selected = GraphWorkspace.open().select()
    assert selected.database.name.value == "env"
    assert selected.source is GraphSelectionSource.ENVIRONMENT


def test_set_default_preserves_other_configuration(tmp_path, monkeypatch):
    _db(tmp_path, "one")
    config_root = tmp_path / "cfg"
    config_dir = config_root / "design-graph"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "config.json"
    config_file.write_text(json.dumps({"graph_dir": str(tmp_path), "custom": True}))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_root))
    monkeypatch.delenv("GRAPH_DIR", raising=False)
    GraphWorkspace.open().set_default("one")
    saved = json.loads(config_file.read_text())
    assert saved == {"graph_dir": str(tmp_path), "custom": True, "default_doc": "one"}


def test_remove_default_database_also_clears_default_doc(tmp_path, monkeypatch):
    database = _db(tmp_path, "old")
    state = tmp_path / "old.db.state.json"
    state.write_text("{}")
    config_root = tmp_path / "cfg"
    config_dir = config_root / "design-graph"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "config.json"
    config_file.write_text(json.dumps({"graph_dir": str(tmp_path), "default_doc": "old"}))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_root))
    monkeypatch.delenv("GRAPH_DIR", raising=False)
    result = GraphWorkspace.open().remove("old")
    assert result.removed_count == 2
    assert not database.exists() and not state.exists()
    assert json.loads(config_file.read_text()) == {"graph_dir": str(tmp_path)}
