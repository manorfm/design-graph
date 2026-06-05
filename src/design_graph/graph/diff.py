"""
Incremental build state management.

Persists the previous build's component/screen fingerprints to disk so that
subsequent builds can skip unchanged prototypes. All logic here is pure —
no Kuzu, no file I/O beyond reading/writing a single JSON state file.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from design_graph.core.models import BuildDiff, BuildState, ExtractedScreen

logger = logging.getLogger(__name__)


def load_state(state_path: Path) -> BuildState:
    """
    Load the previous build state from disk.
    Returns an empty BuildState (first-build equivalent) when the file is
    missing or malformed — never raises.
    """
    if state_path.exists():
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            return BuildState(
                html_hash=data.get("html_hash", ""),
                last_build=data.get("last_build", ""),
                screens=data.get("screens", {}),
                components=data.get("components", {}),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("diff: state file unreadable, treating as first build: %s", exc)

    return BuildState(html_hash="", last_build="", screens={}, components={})


def save_state(state_path: Path, state: BuildState) -> None:
    """Persist the build state. Creates parent directories as needed."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "html_hash":  state.html_hash,
        "last_build": state.last_build,
        "screens":    state.screens,
        "components": state.components,
    }
    state_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.debug("diff: state saved to %s", state_path)


def compute_diff(
    prev: BuildState,
    screens: list[ExtractedScreen],
    comps: Counter,
) -> BuildDiff:
    """
    Compare the previous build state to the current extraction results.
    Pure function — reads only the arguments, writes nothing.
    """
    is_first = not prev.html_hash

    prev_screen_names = set(prev.screens.keys())
    curr_screen_names = {s.name for s in screens}

    prev_comp_names = set(prev.components.keys())
    curr_comp_names  = set(comps.keys())

    return BuildDiff(
        is_first_build=is_first,
        screens_added=sorted(curr_screen_names - prev_screen_names),
        screens_removed=sorted(prev_screen_names - curr_screen_names),
        comps_added=sorted(curr_comp_names - prev_comp_names),
        comps_removed=sorted(prev_comp_names - curr_comp_names),
    )


def compute_screen_hash(screen: ExtractedScreen) -> str:
    """Stable hash for a screen based on its name and component references."""
    key = f"{screen.name}:{','.join(sorted(screen.component_refs))}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def build_new_state(
    html_hash: str,
    screens: list[ExtractedScreen],
    comp_names: Counter,
) -> BuildState:
    """Construct a BuildState from current extraction results."""
    return BuildState(
        html_hash=html_hash,
        last_build=datetime.now(timezone.utc).isoformat(),
        screens={s.name: compute_screen_hash(s) for s in screens},
        components=dict(comp_names.most_common(200)),
    )
