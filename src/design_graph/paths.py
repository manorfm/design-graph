"""
Path resolution for design-graph databases and configuration.

Discovery priority for the graph directory:
  1. GRAPH_DIR env var                          (explicit override)
  2. ~/.config/design-graph/config.json          (user preference)
  3. ~/.local/share/design-graph/               (XDG default)
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def _xdg_data_home() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base)


def _xdg_config_home() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base)


def data_dir() -> Path:
    """~/.local/share/design-graph/ — default location for .db files."""
    return _xdg_data_home() / "design-graph"


def config_dir() -> Path:
    """~/.config/design-graph/ — user configuration directory."""
    return _xdg_config_home() / "design-graph"


def load_user_config() -> dict:
    cfg_file = config_dir() / "config.json"
    if cfg_file.exists():
        try:
            return json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {}


def resolve_graph_dir() -> Path:
    """Return the directory where .db files are stored."""
    env = os.environ.get("GRAPH_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()

    cfg = load_user_config()
    if cfg.get("graph_dir"):
        return Path(cfg["graph_dir"]).expanduser().resolve()

    return data_dir()


def default_db_for(proto_stem: str) -> Path:
    """Return the default .db path for a given prototype file stem."""
    d = resolve_graph_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{proto_stem}.db"
