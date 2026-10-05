"""
Async pipeline coordinator.

Orchestrates a design-graph build, independent of the prototype format:
  Phase 1   — Read the file once and pick the capture that recognizes it
  Phase 2–4 — Capture (format-specific, may run its own work in parallel)
  Phase 5   — Sequential graph writes (Kuzu limitation)
  Phase 6   — State persistence + stats

Writes in phase 5 are always sequential — GraphWriter has no async methods.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

import kuzu

from design_graph.capture.base import (  # UnsupportedPrototypeError: re-exported for entry points
    CaptureResult,
    ComponentProgress,
    PrototypeDocument,
    UnsupportedPrototypeError,
)
from design_graph.capture.registry import capture_for, capture_named
from design_graph.model.build import BuildStats
from design_graph.model.entities import ExtractedComponent
from design_graph.model.graph.diff import compute_diff
from design_graph.model.graph.schema import MODEL_VERSION
from design_graph.model.graph.writer import GraphWriteSession
from design_graph.pipeline.build_progress import BuildPhaseReporter, PhaseTimer, SilentBuildReporter
from design_graph.pipeline.state import build_new_state, load_build_state, save_build_state

logger = logging.getLogger(__name__)

__all__ = ["UnsupportedPrototypeError", "capture_fragment", "capture_prototype", "run_pipeline"]

EXTRACTION_CONCURRENCY = int(os.environ.get("DESIGN_GRAPH_CONCURRENCY", "8"))

# Minimum Kuzu version known to support CONTAINS with properties and
# the connection API used by this pipeline. Older versions may silently
# produce incorrect DDL or fail on edge property writes.
KUZU_MIN_VERSION: tuple[int, ...] = (0, 6)


def check_kuzu_version(version_str: str) -> None:
    """
    Emit a warning to stderr when the installed Kuzu is below KUZU_MIN_VERSION.

    Intentionally non-fatal: a warning is better than refusing to run on
    slightly older installs. The caller (run_pipeline) invokes this once at
    startup so the message appears before any database work begins.
    """
    try:
        parts = tuple(int(x) for x in version_str.split(".")[:2])
    except (ValueError, AttributeError):
        return  # unparseable version string — skip silently

    if parts < KUZU_MIN_VERSION:
        min_str = ".".join(str(x) for x in KUZU_MIN_VERSION)
        sys.stderr.write(
            f"[design-graph] WARNING: Kuzu {version_str} detected; "
            f">= {min_str} recommended for CONTAINS edge property support. "
            "Run: pip install --upgrade kuzu\n"
        )


async def run_pipeline(
    html_path: Path,
    db_path: Path,
    state_path: Path,
    show_diff: bool = False,
    force: bool = False,
    concurrency: int = EXTRACTION_CONCURRENCY,
    reporter: BuildPhaseReporter | None = None,
) -> BuildStats | None:
    """
    Full build pipeline. Returns None when the build is skipped
    (HTML unchanged and force=False).

    Raises FileNotFoundError if html_path does not exist.
    reporter receives phase lifecycle events — defaults to SilentBuildReporter.
    """
    _reporter: BuildPhaseReporter = reporter if reporter is not None else SilentBuildReporter()
    phase = PhaseTimer()
    t_start = time.monotonic()
    check_kuzu_version(kuzu.__version__)

    # ── Phase 1: Load ─────────────────────────────────────────────────────────
    _reporter.phase_started(f"Loading {html_path.name}", total=0)
    phase.start()
    document = await asyncio.to_thread(PrototypeDocument.read, html_path)
    _reporter.phase_completed(f"Loading {html_path.name}", elapsed_seconds=phase.split())
    capture = capture_for(document)
    logger.info(
        "pipeline: loaded %s (hash=%s, capture=%s)", html_path.name, document.digest[:8], capture.name,
    )

    prev_state = load_build_state(state_path)
    if (
        not force and db_path.exists()
        and prev_state.html_hash == document.digest
        and prev_state.schema_version == MODEL_VERSION
    ):
        logger.info("pipeline: skipping unchanged prototype %s", html_path.name)
        _reporter.build_skipped("HTML unchanged — use --force to rebuild")
        return None

    # ── Phase 2–4: Capture ────────────────────────────────────────────────────
    _reporter.phase_started("Parsing boundaries and tokens", total=0)
    phase.start()
    result = await capture.capture(
        document,
        concurrency=concurrency,
        on_component_extracted=lambda name, idx, total: _reporter.component_extracted(
            name, index=idx, total=total
        ),
    )
    extracted_comps = result.components
    screens         = result.screens
    sections_map    = result.sections
    tokens          = result.tokens
    module_texts    = result.module_texts
    _reporter.phase_completed(
        "Parsing boundaries and tokens",
        elapsed_seconds=phase.split(),
        total=len(extracted_comps) + len(tokens),
    )

    icons_by_id = {icon.id: icon for comp in extracted_comps for icon in comp.icons}
    icons_by_id.update({icon.id: icon for screen in screens for icon in screen.icons})
    icons = list(icons_by_id.values())

    for screen in screens:
        screen.sections_count = len(sections_map.get(screen.name, []))

    logger.info(
        "pipeline: %d screens, %d components, %d tokens, %d icons, %d module texts (capture=%s)",
        len(screens), len(extracted_comps), len(tokens), len(icons), len(module_texts), result.capture,
    )

    # ── Phase 5: Sequential graph writes (atomic via GraphWriteSession) ──────
    write_total = len(extracted_comps) + len(screens) + len(tokens) + len(icons) + len(module_texts)
    _reporter.phase_started("Writing graph", total=write_total)
    phase.start()

    raw_stats: dict[str, int] = {}
    with GraphWriteSession(db_path) as writer:
        writer.record_model(result.capture)
        writer.write_tokens(tokens)
        writer.write_icons(icons)
        writer.write_module_texts(module_texts)
        writer.declare_screens(screens)
        item_index = len(tokens) + len(icons) + len(module_texts)

        for comp in extracted_comps:
            writer.write_component(comp)
            item_index += 1
            _reporter.item_written(comp.name, index=item_index, total=write_total)

        flushed = writer.flush_pending_contains()
        if flushed:
            logger.debug("pipeline: flushed %d deferred CONTAINS edges", flushed)

        for screen in screens:
            writer.write_screen(screen, sections_map.get(screen.name, []))
            item_index += 1
            _reporter.item_written(screen.name, index=item_index, total=write_total)

        writer.commit()
        # Collect stats while the write connection is still open
        raw_stats = writer.get_stats()

    if raw_stats.get("write_errors", 0) > 0:
        logger.warning(
            "pipeline: %d non-duplicate write errors during this build — "
            "the graph may be missing nodes or edges; rerun with --verbose for details",
            raw_stats["write_errors"],
        )

    _reporter.phase_completed("Writing graph", elapsed_seconds=phase.split())

    # ── Phase 6: State persistence ───────────────────────────────────────────
    comp_counter = Counter({c.name: c.occurrence for c in extracted_comps})
    # Computed unconditionally (not just when show_diff/--diff is passed) so
    # it can be persisted for get_build_diff — an MCP agent asking "what
    # changed since I last looked" shouldn't depend on the CLI user having
    # happened to pass --diff on their last build.
    diff = compute_diff(prev_state, screens, comp_counter)
    save_build_state(state_path, build_new_state(
        document.digest, screens, comp_counter,
        source_path=html_path, database_path=db_path, diff=diff,
        skipped_entries=result.skipped_entries,
    ))
    elapsed = time.monotonic() - t_start

    stats = BuildStats(
        screens=raw_stats.get("screens", 0),
        components=raw_stats.get("components", 0),
        extracted_components=raw_stats.get("extracted_components", 0),
        unresolved_components=raw_stats.get("unresolved_components", 0),
        tokens=raw_stats.get("tokens", 0),
        icons=raw_stats.get("icons", 0),
        sections=raw_stats.get("sections", 0),
        interactions=raw_stats.get("interactions", 0),
        styles=raw_stats.get("styles", 0),
        texts=raw_stats.get("texts", 0),
        contains_rels=raw_stats.get("contains", 0),
        component_props=raw_stats.get("component_props", 0),
        section_styles=raw_stats.get("section_styles", 0),
        write_errors=raw_stats.get("write_errors", 0),
        duration_seconds=elapsed,
    )

    if show_diff:
        _log_diff(diff)

    _reporter.build_completed(total_seconds=elapsed)
    logger.info(
        "pipeline: build complete in %.2fs — "
        "screens=%d comps=%d tokens=%d sections=%d contains=%d",
        elapsed, stats.screens, stats.components, stats.tokens,
        stats.sections, stats.contains_rels,
    )
    return stats


async def capture_prototype(
    html_path: Path,
    concurrency: int = EXTRACTION_CONCURRENCY,
    on_component_extracted: ComponentProgress | None = None,
) -> CaptureResult:
    """Read a prototype and run the capture that recognizes it, without writing a graph."""
    document = await asyncio.to_thread(PrototypeDocument.read, html_path)
    return await capture_for(document).capture(
        document, concurrency=concurrency, on_component_extracted=on_component_extracted,
    )


def capture_fragment(capture_name: str, source: str) -> ExtractedComponent | None:
    """
    Read a standalone fragment with the capture a prototype was built with.
    Raises UnsupportedPrototypeError when no capture of that name exists.
    """
    return capture_named(capture_name).capture_fragment(source)


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
