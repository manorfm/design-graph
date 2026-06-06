"""
Pure diff computation for the build pipeline.

Compares two BuildState snapshots to produce a BuildDiff describing what changed
between builds. No file I/O — that responsibility belongs to pipeline/state.py.
"""

from __future__ import annotations

import hashlib
import logging
from collections import Counter

from design_graph.core.models import BuildDiff, BuildState, ExtractedScreen

logger = logging.getLogger(__name__)


def compute_diff(
    prev: BuildState,
    screens: list[ExtractedScreen],
    comps: Counter,
) -> BuildDiff:
    """
    Compare the previous build state to the current extraction results.

    Pure function — reads only the arguments, writes nothing.
    Returns a BuildDiff describing additions and removals since last build.
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
    """Stable 12-char hex fingerprint of a screen based on name + component refs."""
    key = f"{screen.name}:{','.join(sorted(screen.component_refs))}"
    return hashlib.md5(key.encode()).hexdigest()[:12]
