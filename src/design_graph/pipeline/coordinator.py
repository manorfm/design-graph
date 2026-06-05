"""
Async pipeline coordinator.

Orchestrates the six phases of a design-graph build:
  Phase 1 — File I/O (sequential: one file)
  Phase 2 — Parallel token extraction + function boundary detection
  Phase 3 — Parallel component extraction (one coroutine per component)
  Phase 4 — Parallel section extraction (one coroutine per screen)
  Phase 5 — Sequential graph writes (Kuzu limitation)
  Phase 6 — State persistence + stats

The JS string is immutable; concurrent reads in phases 2-4 are safe.
Writes in phase 5 are always sequential — GraphWriter has no async methods.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from collections import Counter
from pathlib import Path

import kuzu

from design_graph.core.models import BuildStats, ExtractedScreen, FunctionBoundary
from design_graph.extraction.component_extractor import extract_all_components
from design_graph.extraction.screen_extractor import extract_screens, is_screen
from design_graph.extraction.section_extractor import extract_sections
from design_graph.graph.diff import build_new_state, compute_diff, load_state, save_state
from design_graph.graph.schema import initialize_schema
from design_graph.graph.writer import GraphWriter
from design_graph.parsing.js_parser import find_all_boundaries
from design_graph.parsing.source_loader import load
from design_graph.parsing.token_extractor import build_token_map, extract_tokens

logger = logging.getLogger(__name__)

EXTRACTION_CONCURRENCY = int(os.environ.get("DESIGN_GRAPH_CONCURRENCY", "8"))


async def run_pipeline(
    html_path: Path,
    db_path: Path,
    state_path: Path,
    show_diff: bool = False,
    force: bool = False,
    concurrency: int = EXTRACTION_CONCURRENCY,
) -> BuildStats | None:
    """
    Full build pipeline. Returns None when the build is skipped
    (HTML unchanged and force=False).

    Raises FileNotFoundError if html_path does not exist.
    """
    t_start = time.monotonic()

    # ── Phase 1: File I/O ─────────────────────────────────────────────────────
    sources = await load(html_path)
    logger.info("pipeline: loaded %s (hash=%s)", html_path.name, sources.html_hash[:8])

    prev_state = load_state(state_path)
    if not force and prev_state.html_hash == sources.html_hash:
        logger.info("pipeline: skipping unchanged prototype %s", html_path.name)
        return None

    # ── Phase 2: Parallel reads on RawSources ────────────────────────────────
    tokens_task    = asyncio.create_task(asyncio.to_thread(extract_tokens, sources))
    boundaries_task = asyncio.create_task(asyncio.to_thread(find_all_boundaries, sources.js))
    tokens, all_boundaries = await asyncio.gather(tokens_task, boundaries_task)

    token_map     = build_token_map(tokens)
    screen_bounds = [b for b in all_boundaries if is_screen(b.name)]
    comp_bounds   = [b for b in all_boundaries if not is_screen(b.name)]
    occurrences   = Counter(b.name for b in all_boundaries)

    logger.info(
        "pipeline: %d screens, %d components, %d tokens detected",
        len(screen_bounds), len(comp_bounds), len(tokens),
    )

    # ── Phase 3: Parallel component extraction ───────────────────────────────
    extracted_comps = await extract_all_components(
        sources.js, comp_bounds, occurrences, token_map, concurrency=concurrency
    )

    # ── Phase 4: Parallel section extraction ─────────────────────────────────
    screens = extract_screens(sources.js, all_boundaries)
    screen_bound_map: dict[str, FunctionBoundary] = {b.name: b for b in screen_bounds}
    sem = asyncio.Semaphore(concurrency)

    async def _extract_sections_for(screen: ExtractedScreen):
        boundary = screen_bound_map.get(screen.name)
        if not boundary:
            return screen.name, []
        async with sem:
            secs = await asyncio.to_thread(extract_sections, sources.js, screen, boundary)
            return screen.name, secs

    section_pairs = await asyncio.gather(*[_extract_sections_for(s) for s in screens])
    sections_map: dict[str, list] = dict(section_pairs)

    for screen in screens:
        screen.sections_count = len(sections_map.get(screen.name, []))

    # ── Phase 5: Sequential graph writes ────────────────────────────────────
    _rebuild_db(db_path)
    db   = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)
    initialize_schema(conn)
    writer = GraphWriter(conn)

    writer.write_tokens(tokens)
    for comp in extracted_comps:
        writer.write_component(comp, token_map)
    for screen in screens:
        writer.write_screen(screen, sections_map.get(screen.name, []), token_map)

    # ── Phase 6: State + stats ───────────────────────────────────────────────
    comp_counter = Counter({c.name: c.occurrence for c in extracted_comps})
    save_state(state_path, build_new_state(sources.html_hash, screens, comp_counter))

    raw_stats = writer.get_stats()
    elapsed = time.monotonic() - t_start

    stats = BuildStats(
        screens=raw_stats.get("screens", 0),
        components=raw_stats.get("components", 0),
        tokens=raw_stats.get("tokens", 0),
        sections=raw_stats.get("sections", 0),
        interactions=raw_stats.get("interactions", 0),
        styles=raw_stats.get("styles", 0),
        texts=raw_stats.get("texts", 0),
        contains_rels=raw_stats.get("contains", 0),
        duration_seconds=elapsed,
    )

    if show_diff:
        diff = compute_diff(prev_state, screens, comp_counter)
        _log_diff(diff)

    logger.info(
        "pipeline: build complete in %.2fs — "
        "screens=%d comps=%d tokens=%d sections=%d contains=%d",
        elapsed, stats.screens, stats.components, stats.tokens,
        stats.sections, stats.contains_rels,
    )
    return stats


# ── Private helpers ───────────────────────────────────────────────────────────

def _rebuild_db(db_path: Path) -> None:
    """Remove any existing database at db_path before creating a fresh one."""
    if db_path.exists():
        if db_path.is_dir():
            shutil.rmtree(str(db_path), ignore_errors=True)
        else:
            db_path.unlink(missing_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)


def _log_diff(diff) -> None:
    if diff.is_first_build:
        logger.info("diff: first build")
        return
    if diff.screens_added:
        logger.info("diff: screens added: %s", ", ".join(diff.screens_added))
    if diff.screens_removed:
        logger.info("diff: screens removed: %s", ", ".join(diff.screens_removed))
    if diff.comps_added:
        logger.info("diff: %d new components", len(diff.comps_added))
    if diff.comps_removed:
        logger.info("diff: %d removed components", len(diff.comps_removed))
