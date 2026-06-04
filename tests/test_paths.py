"""Tests for _paths.py — layered graph directory resolution."""
import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch

from _paths import (
    resolve_graph_dir,
    default_db_for,
    load_user_config,
    data_dir,
    config_dir,
)


class TestResolveGraphDir:
    def test_env_var_takes_priority(self, tmp_path):
        with patch.dict(os.environ, {"GRAPH_DIR": str(tmp_path)}, clear=False):
            assert resolve_graph_dir() == tmp_path

    def test_env_var_expands_tilde(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GRAPH_DIR", "~/graphs")
        result = resolve_graph_dir()
        assert not str(result).startswith("~")

    def test_config_file_used_when_no_env(self, tmp_path):
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"graph_dir": str(tmp_path)}))
        with patch("_paths.config_dir", return_value=tmp_path):
            with patch.dict(os.environ, {}, clear=False):
                env = {k: v for k, v in os.environ.items() if k != "GRAPH_DIR"}
                with patch.dict(os.environ, env, clear=True):
                    assert resolve_graph_dir() == tmp_path

    def test_xdg_default_fallback(self, tmp_path):
        env = {k: v for k, v in os.environ.items() if k != "GRAPH_DIR"}
        with patch.dict(os.environ, env, clear=True):
            with patch("_paths._xdg_data_home", return_value=tmp_path):
                with patch("_paths.load_user_config", return_value={}):
                    result = resolve_graph_dir()
                    assert result == tmp_path / "design-graph"

    def test_env_overrides_config_file(self, tmp_path):
        other = tmp_path / "other"
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"graph_dir": str(other)}))
        with patch("_paths.config_dir", return_value=tmp_path):
            with patch.dict(os.environ, {"GRAPH_DIR": str(tmp_path)}, clear=False):
                assert resolve_graph_dir() == tmp_path


class TestDefaultDbFor:
    def test_returns_db_path(self, tmp_path):
        with patch("_paths.resolve_graph_dir", return_value=tmp_path):
            result = default_db_for("myapp")
            assert result == tmp_path / "myapp.db"

    def test_creates_directory_if_missing(self, tmp_path):
        target = tmp_path / "new-dir"
        with patch("_paths.resolve_graph_dir", return_value=target):
            default_db_for("myapp")
            assert target.exists()

    def test_stem_becomes_filename(self, tmp_path):
        with patch("_paths.resolve_graph_dir", return_value=tmp_path):
            assert default_db_for("admin-panel").name == "admin-panel.db"


class TestLoadUserConfig:
    def test_returns_empty_when_file_missing(self, tmp_path):
        with patch("_paths.config_dir", return_value=tmp_path / "nonexistent"):
            assert load_user_config() == {}

    def test_returns_empty_on_malformed_json(self, tmp_path):
        (tmp_path / "config.json").write_text("not json {{")
        with patch("_paths.config_dir", return_value=tmp_path):
            assert load_user_config() == {}

    def test_parses_valid_config(self, tmp_path):
        (tmp_path / "config.json").write_text(json.dumps({"graph_dir": "/some/path"}))
        with patch("_paths.config_dir", return_value=tmp_path):
            cfg = load_user_config()
            assert cfg["graph_dir"] == "/some/path"

    def test_returns_empty_on_permission_error(self, tmp_path):
        cfg = tmp_path / "config.json"
        cfg.write_text("{}")
        cfg.chmod(0o000)
        with patch("_paths.config_dir", return_value=tmp_path):
            result = load_user_config()
            assert result == {}
        cfg.chmod(0o644)
