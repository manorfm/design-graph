"""
Build-state persistence for the pipeline coordinator.

Responsible for reading and writing the .graph-state.json file that enables
incremental builds (skip unchanged prototypes) and diff reporting.

Separation of concerns:
  - This module owns file I/O and state construction.
  - graph/diff.py owns pure diff computation (compare two BuildState objects).
  - pipeline/coordinator.py owns orchestration (when to load/save state).
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from design_graph.core.models import BuildState, ExtractedScreen

logger = logging.getLogger(__name__)

_EMPTY_STATE = BuildState(html_hash="", last_build="", screens={}, components={})


def load_build_state(state_path: Path) -> BuildState:
    """
    Load the previous build state from disk.

    Returns an empty BuildState (first-build equivalent) when the file is
    missing, unreadable, or contains unexpected structure — never raises.
    """
    if not state_path.exists():
        return _empty_build_state()

    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("state file is not a JSON object")
        return BuildState(
            html_hash=data.get("html_hash", ""),
            last_build=data.get("last_build", ""),
            screens=data.get("screens", {}),
            components=data.get("components", {}),
        )
    except Exception as exc:
        logger.warning(
            "state: unreadable build state at %s, treating as first build: %s",
            state_path, exc,
        )
        return _empty_build_state()


def save_build_state(state_path: Path, state: BuildState) -> None:
    """
    Persist the build state to disk. Creates parent directories as needed.

    The file is written atomically (write to disk then rename) to avoid
    leaving a corrupt state file if the process is interrupted mid-write.
    """
    state_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "html_hash":  state.html_hash,
        "last_build": state.last_build,
        "screens":    state.screens,
        "components": state.components,
    }
    tmp_path = state_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(state_path)

    logger.debug("state: saved to %s", state_path)


def build_new_state(
    html_hash: str,
    screens: list[ExtractedScreen],
    comp_counts: Counter,
) -> BuildState:
    """
    Construct a BuildState snapshot from the current extraction results.

    Stores the top 200 components by occurrence count — enough for diff
    reporting without unbounded growth on large prototypes.
    """
    return BuildState(
        html_hash=html_hash,
        last_build=datetime.now(timezone.utc).isoformat(),
        screens={s.name: _screen_fingerprint(s) for s in screens},
        components=dict(comp_counts.most_common(200)),
    )


# ── private ───────────────────────────────────────────────────────────────────

def _empty_build_state() -> BuildState:
    return BuildState(html_hash="", last_build="", screens={}, components={})


def _screen_fingerprint(screen: ExtractedScreen) -> str:
    """Stable 12-char hex fingerprint of a screen based on name + component refs."""
    key = f"{screen.name}:{','.join(sorted(screen.component_refs))}"
    return hashlib.md5(key.encode()).hexdigest()[:12]
