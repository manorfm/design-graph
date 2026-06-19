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

import hashlib
import json
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from design_graph.core.models import BuildState, ExtractedScreen

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
        source_path=str(source_path.resolve()) if source_path else "",
        database_path=str(database_path.resolve()) if database_path else "",
        schema_version=2,
    )


# ── private ───────────────────────────────────────────────────────────────────

def _empty_build_state() -> BuildState:
    return BuildState(html_hash="", last_build="", screens={}, components={})


def _screen_fingerprint(screen: ExtractedScreen) -> str:
    """Stable 12-char hex fingerprint of a screen based on name + component refs."""
    key = f"{screen.name}:{','.join(sorted(screen.component_refs))}"
    return hashlib.md5(key.encode()).hexdigest()[:12]
