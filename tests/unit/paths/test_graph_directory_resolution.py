"""
Unit tests for design_graph.paths — graph directory and config resolution.

Verifies the three-tier priority chain:
  1. GRAPH_DIR env var  (highest priority, explicit override)
  2. ~/.config/design-graph/config.json  graph_dir key
  3. ~/.local/share/design-graph/  (XDG default, lowest priority)

All tests use monkeypatching or tmp_path so they never touch the real
file system or the caller's environment variables.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from design_graph.paths import (
    config_dir,
    data_dir,
    default_db_for,
    load_user_config,
    resolve_graph_dir,
)


# ── resolve_graph_dir ─────────────────────────────────────────────────────────

class TestResolveGraphDir:
    def test_env_var_takes_highest_priority(self, tmp_path):
        with patch.dict(os.environ, {"GRAPH_DIR": str(tmp_path)}, clear=False):
            assert resolve_graph_dir() == tmp_path

    def test_env_var_expands_tilde(self, monkeypatch):
        monkeypatch.setenv("GRAPH_DIR", "~/my_graphs")
        result = resolve_graph_dir()
        assert not str(result).startswith("~")
        assert "my_graphs" in str(result)

    def test_config_file_used_when_env_absent(self, tmp_path):
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"graph_dir": str(tmp_path)}), encoding="utf-8")
        env_without_graph_dir = {k: v for k, v in os.environ.items() if k != "GRAPH_DIR"}
        with patch("design_graph.paths.config_dir", return_value=tmp_path):
            with patch.dict(os.environ, env_without_graph_dir, clear=True):
                assert resolve_graph_dir() == tmp_path

    def test_xdg_default_when_no_env_and_no_config(self, tmp_path):
        env_without_graph_dir = {k: v for k, v in os.environ.items() if k != "GRAPH_DIR"}
        with patch("design_graph.paths._xdg_data_home", return_value=tmp_path):
            with patch("design_graph.paths.load_user_config", return_value={}):
                with patch.dict(os.environ, env_without_graph_dir, clear=True):
                    result = resolve_graph_dir()
                    assert result == tmp_path / "design-graph"

    def test_env_var_overrides_config_file(self, tmp_path):
        config_target = tmp_path / "config_target"
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"graph_dir": str(config_target)}), encoding="utf-8")
        with patch("design_graph.paths.config_dir", return_value=tmp_path):
            with patch.dict(os.environ, {"GRAPH_DIR": str(tmp_path)}, clear=False):
                assert resolve_graph_dir() == tmp_path

    def test_returns_path_object(self, tmp_path):
        with patch.dict(os.environ, {"GRAPH_DIR": str(tmp_path)}, clear=False):
            result = resolve_graph_dir()
            assert isinstance(result, Path)

    def test_whitespace_only_env_var_falls_through(self, tmp_path):
        with patch.dict(os.environ, {"GRAPH_DIR": "   "}, clear=False):
            with patch("design_graph.paths._xdg_data_home", return_value=tmp_path):
                with patch("design_graph.paths.load_user_config", return_value={}):
                    result = resolve_graph_dir()
                    assert result == tmp_path / "design-graph"


# ── default_db_for ────────────────────────────────────────────────────────────

class TestDefaultDbFor:
    def test_returns_path_with_db_extension(self, tmp_path):
        with patch("design_graph.paths.resolve_graph_dir", return_value=tmp_path):
            result = default_db_for("myapp")
            assert result == tmp_path / "myapp.db"

    def test_creates_parent_directory_when_missing(self, tmp_path):
        target_dir = tmp_path / "new_graphs_dir"
        with patch("design_graph.paths.resolve_graph_dir", return_value=target_dir):
            default_db_for("myapp")
            assert target_dir.exists()

    def test_stem_becomes_filename(self, tmp_path):
        with patch("design_graph.paths.resolve_graph_dir", return_value=tmp_path):
            assert default_db_for("admin-panel").name == "admin-panel.db"

    def test_stem_preserved_with_hyphens(self, tmp_path):
        with patch("design_graph.paths.resolve_graph_dir", return_value=tmp_path):
            result = default_db_for("ipede-v7")
            assert result.stem == "ipede-v7"

    def test_returns_path_object(self, tmp_path):
        with patch("design_graph.paths.resolve_graph_dir", return_value=tmp_path):
            assert isinstance(default_db_for("x"), Path)


# ── load_user_config ──────────────────────────────────────────────────────────

class TestLoadUserConfig:
    def test_returns_empty_dict_when_config_file_missing(self, tmp_path):
        with patch("design_graph.paths.config_dir", return_value=tmp_path / "nonexistent"):
            assert load_user_config() == {}

    def test_returns_empty_dict_on_malformed_json(self, tmp_path):
        (tmp_path / "config.json").write_text("not { valid json {{", encoding="utf-8")
        with patch("design_graph.paths.config_dir", return_value=tmp_path):
            assert load_user_config() == {}

    def test_parses_valid_config_file(self, tmp_path):
        (tmp_path / "config.json").write_text(
            json.dumps({"graph_dir": "/custom/path", "other_key": 42}),
            encoding="utf-8",
        )
        with patch("design_graph.paths.config_dir", return_value=tmp_path):
            cfg = load_user_config()
            assert cfg["graph_dir"] == "/custom/path"
            assert cfg["other_key"] == 42

    def test_returns_dict_type(self, tmp_path):
        (tmp_path / "config.json").write_text("{}", encoding="utf-8")
        with patch("design_graph.paths.config_dir", return_value=tmp_path):
            assert isinstance(load_user_config(), dict)

    def test_never_raises_on_unreadable_file(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text("{}", encoding="utf-8")
        cfg_file.chmod(0o000)
        try:
            with patch("design_graph.paths.config_dir", return_value=tmp_path):
                result = load_user_config()
                assert result == {}
        finally:
            cfg_file.chmod(0o644)

    def test_empty_file_returns_empty_dict(self, tmp_path):
        (tmp_path / "config.json").write_text("", encoding="utf-8")
        with patch("design_graph.paths.config_dir", return_value=tmp_path):
            assert load_user_config() == {}


# ── data_dir and config_dir ───────────────────────────────────────────────────

class TestXdgDirectories:
    def test_data_dir_under_xdg_data_home(self, tmp_path):
        with patch("design_graph.paths._xdg_data_home", return_value=tmp_path):
            assert data_dir() == tmp_path / "design-graph"

    def test_config_dir_under_xdg_config_home(self, tmp_path):
        with patch("design_graph.paths._xdg_config_home", return_value=tmp_path):
            assert config_dir() == tmp_path / "design-graph"

    def test_data_dir_uses_xdg_env_var(self, tmp_path):
        with patch.dict(os.environ, {"XDG_DATA_HOME": str(tmp_path)}, clear=False):
            assert data_dir() == tmp_path / "design-graph"

    def test_config_dir_uses_xdg_env_var(self, tmp_path):
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(tmp_path)}, clear=False):
            assert config_dir() == tmp_path / "design-graph"
