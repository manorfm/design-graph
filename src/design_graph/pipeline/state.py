"""
Per-database build-state persistence for the pipeline coordinator.

Responsible for reading and writing each <database>.state.json file that enables
incremental builds (skip unchanged prototypes) and diff reporting.

Separation of concerns:
  - This module owns file I/O and state construction.
  - graph/diff.py owns pure diff computation (compare two BuildState objects).
  - pipeline/coordinator.py owns orchestration (when to load/save state).
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from design_graph.core.models import BuildDiff, BuildState, ExtractedScreen
from design_graph.graph.diff import compute_screen_hash

logger = logging.getLogger(__name__)

_EMPTY_STATE = BuildState(html_hash="", last_build="", screens={}, components={})


@dataclass(frozen=True)
class BuildStateRepository:
    """Owns persistence for the incremental state of exactly one database."""

    database_path: Path

    @classmethod
    def for_database(cls, db_path: Path) -> "BuildStateRepository":
        return cls(db_path)

    @property
    def path(self) -> Path:
        return self.database_path.with_name(f"{self.database_path.name}.state.json")

    def load(self) -> BuildState:
        return load_build_state(self.path)

    def save(self, state: BuildState) -> None:
        save_build_state(self.path, state)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)

    def migrate_legacy(self, legacy_path: Path, known_databases: tuple[Path, ...]) -> bool:
        """Adopt the shared legacy state only when ownership is unambiguous."""
        known = tuple(path.resolve() for path in known_databases)
        ownership_is_clear = not known or (
            len(known) == 1 and known[0] == self.database_path.resolve()
        )
        if self.path.exists() or not legacy_path.exists() or not ownership_is_clear:
            return False
        legacy_path.replace(self.path)
        return True


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
            source_path=data.get("source_path", ""),
            database_path=data.get("database_path", ""),
            schema_version=int(data.get("schema_version", 1)),
            last_diff=_diff_from_payload(data.get("last_diff")),
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
        "source_path": state.source_path,
        "database_path": state.database_path,
        "schema_version": state.schema_version,
        "last_diff": _diff_to_payload(state.last_diff),
    }
    tmp_path = state_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(state_path)

    logger.debug("state: saved to %s", state_path)


def build_new_state(
    html_hash: str,
    screens: list[ExtractedScreen],
    comp_counts: Counter,
    source_path: Path | None = None,
    database_path: Path | None = None,
    diff: BuildDiff | None = None,
) -> BuildState:
    """
    Construct a BuildState snapshot from the current extraction results.

    Stores the top 200 components by occurrence count — enough for diff
    reporting without unbounded growth on large prototypes.

    diff: this build's own BuildDiff (relative to the state it replaces),
    persisted so a later caller — the MCP get_build_diff tool, in
    particular — can answer "what changed since the last build" by just
    reading this file, without recomputing anything or comparing two
    Kuzu databases from scratch.
    """
    return BuildState(
        html_hash=html_hash,
        last_build=datetime.now(timezone.utc).isoformat(),
        screens={s.name: compute_screen_hash(s) for s in screens},
        components=dict(comp_counts.most_common(200)),
        source_path=str(source_path.resolve()) if source_path else "",
        database_path=str(database_path.resolve()) if database_path else "",
        schema_version=2,
        last_diff=diff,
    )


# ── private ───────────────────────────────────────────────────────────────────

def _empty_build_state() -> BuildState:
    return BuildState(html_hash="", last_build="", screens={}, components={})


def _diff_to_payload(diff: BuildDiff | None) -> dict | None:
    if diff is None:
        return None
    return {
        "is_first_build":  diff.is_first_build,
        "screens_added":   diff.screens_added,
        "screens_removed": diff.screens_removed,
        "comps_added":     diff.comps_added,
        "comps_removed":   diff.comps_removed,
    }


def _diff_from_payload(data) -> BuildDiff | None:
    if not isinstance(data, dict):
        return None
    try:
        return BuildDiff(
            is_first_build=bool(data.get("is_first_build", False)),
            screens_added=list(data.get("screens_added", [])),
            screens_removed=list(data.get("screens_removed", [])),
            comps_added=list(data.get("comps_added", [])),
            comps_removed=list(data.get("comps_removed", [])),
        )
    except Exception:  # noqa: BLE001
        # Malformed/legacy payload — no diff available is a safe default,
        # same "treat as absent" fallback load_build_state already applies
        # to the whole file being unreadable.
        return None
