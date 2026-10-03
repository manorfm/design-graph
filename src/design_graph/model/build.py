"""Build bookkeeping: what a build produced and what changed since the last one."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BuildState:
    """Persisted state from the previous build run (for incremental builds)."""

    html_hash: str
    last_build: str            # ISO datetime string
    screens: dict[str, str]    # name → content hash
    components: dict[str, int] # name → occurrence count
    source_path: str = ""
    database_path: str = ""
    schema_version: int = 2
    last_diff: "BuildDiff | None" = None  # what this build changed relative to the one before it
    skipped_entries: int = 0


@dataclass(frozen=True)
class BuildDiff:
    """What changed between the previous and current build."""

    is_first_build: bool
    screens_added: list[str]
    screens_removed: list[str]
    comps_added: list[str]
    comps_removed: list[str]


@dataclass
class BuildStats:
    """Counts of graph nodes/edges after a completed build."""

    screens: int = 0
    components: int = 0
    extracted_components: int = 0
    unresolved_components: int = 0
    tokens: int = 0
    icons: int = 0
    sections: int = 0
    interactions: int = 0
    styles: int = 0
    texts: int = 0
    contains_rels: int = 0
    component_props: int = 0   # ComponentProp nodes from function signature extraction
    section_styles: int = 0    # SECTION_HAS_STYLE edges for section container styles
    write_errors: int = 0      # Non-duplicate write failures during this build (should be 0)
    duration_seconds: float = 0.0

