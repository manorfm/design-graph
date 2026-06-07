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
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Callable

import kuzu

from design_graph.core.models import BuildStats, ExtractedScreen, FunctionBoundary
from design_graph.pipeline.build_progress import BuildPhaseReporter, PhaseTimer, SilentBuildReporter
from design_graph.extraction.component_extractor import extract_all_components
from design_graph.extraction.plain_html_component_extractor import dom_patterns_to_extracted_components
from design_graph.extraction.screen_extractor import extract_screens, is_screen
from design_graph.extraction.section_extractor import extract_sections, extract_sections_for_plain_html
from design_graph.graph.diff import compute_diff
from design_graph.pipeline.state import build_new_state, load_build_state, save_build_state
from design_graph.graph.writer import GraphWriteSession
from design_graph.parsing.css_class_resolver import extract_css_rules
from design_graph.parsing.format_detector import PLAIN_HTML
from design_graph.parsing.js_parser import find_all_boundaries
from design_graph.parsing.source_loader import load
from design_graph.parsing.token_extractor import build_token_map, extract_tokens

logger = logging.getLogger(__name__)

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
    sources = await load(html_path)
    logger.info("pipeline: loaded %s (hash=%s)", html_path.name, sources.html_hash[:8])
    _reporter.phase_completed(f"Loading {html_path.name}", elapsed_seconds=phase.split())

    prev_state = load_build_state(state_path)
    if not force and prev_state.html_hash == sources.html_hash:
        logger.info("pipeline: skipping unchanged prototype %s", html_path.name)
        _reporter.build_skipped("HTML unchanged — use --force to rebuild")
        return None

    # ── Phase 2–4: Format-specific extraction ────────────────────────────────
    # Use the plain HTML DOM-pattern path only when the file has NO React/JSX
    # function definitions. A plain_html file with PascalCase functions (like
    # simple.html with inline React) still uses the JS boundary extraction path.
    _reporter.phase_started("Parsing boundaries and tokens", total=0)
    phase.start()
    if sources.format == PLAIN_HTML and not _has_react_functions(sources.js):
        extracted_comps, screens, sections_map, tokens = await _extract_plain_html(
            sources, concurrency=concurrency
        )
    else:
        extracted_comps, screens, sections_map, tokens = await _extract_react(
            sources,
            concurrency=concurrency,
            on_component_extracted=lambda name, idx, total: _reporter.component_extracted(
                name, index=idx, total=total
            ),
        )
    _reporter.phase_completed(
        "Parsing boundaries and tokens",
        elapsed_seconds=phase.split(),
        total=len(extracted_comps) + len(tokens),
    )

    token_map = build_token_map(tokens)

    for screen in screens:
        screen.sections_count = len(sections_map.get(screen.name, []))

    logger.info(
        "pipeline: %d screens, %d components, %d tokens (format=%s)",
        len(screens), len(extracted_comps), len(tokens), sources.format,
    )

    # ── Phase 5: Sequential graph writes (atomic via GraphWriteSession) ──────
    write_total = len(extracted_comps) + len(screens) + len(tokens)
    _reporter.phase_started("Writing graph", total=write_total)
    phase.start()

    raw_stats: dict[str, int] = {}
    with GraphWriteSession(db_path) as writer:
        writer.write_tokens(tokens)
        item_index = len(tokens)

        for comp in extracted_comps:
            writer.write_component(comp, token_map)
            item_index += 1
            _reporter.item_written(comp.name, index=item_index, total=write_total)

        flushed = writer.flush_pending_contains()
        if flushed:
            logger.debug("pipeline: flushed %d deferred CONTAINS edges", flushed)

        for screen in screens:
            writer.write_screen(screen, sections_map.get(screen.name, []), token_map)
            item_index += 1
            _reporter.item_written(screen.name, index=item_index, total=write_total)

        # Collect stats while the write connection is still open
        raw_stats = writer.get_stats()

    _reporter.phase_completed("Writing graph", elapsed_seconds=phase.split())

    # ── Phase 6: State persistence ───────────────────────────────────────────
    comp_counter = Counter({c.name: c.occurrence for c in extracted_comps})
    save_build_state(state_path, build_new_state(sources.html_hash, screens, comp_counter))
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
        component_props=raw_stats.get("component_props", 0),
        section_styles=raw_stats.get("section_styles", 0),
        duration_seconds=elapsed,
    )

    if show_diff:
        diff = compute_diff(prev_state, screens, comp_counter)
        _log_diff(diff)

    _reporter.build_completed(total_seconds=elapsed)
    logger.info(
        "pipeline: build complete in %.2fs — "
        "screens=%d comps=%d tokens=%d sections=%d contains=%d",
        elapsed, stats.screens, stats.components, stats.tokens,
        stats.sections, stats.contains_rels,
    )
    return stats


# ── Private helpers ───────────────────────────────────────────────────────────

async def _extract_react(
    sources,
    concurrency: int,
    on_component_extracted: Callable[[str, int, int], None] | None = None,
) -> tuple[list, list, dict, list]:
    """
    Phases 2–4 for bundled_react and tailwind formats.
    Returns (extracted_comps, screens, sections_map, tokens).

    on_component_extracted: forwarded to extract_all_components so the caller
        can display per-component extraction progress without importing extraction internals.
    """
    tokens_task     = asyncio.create_task(asyncio.to_thread(extract_tokens, sources))
    boundaries_task = asyncio.create_task(asyncio.to_thread(find_all_boundaries, sources.js))
    tokens, all_boundaries = await asyncio.gather(tokens_task, boundaries_task)

    token_map     = build_token_map(tokens)
    rule_map      = extract_css_rules(sources.css) if sources.css else {}
    screen_bounds = [b for b in all_boundaries if is_screen(b.name)]
    comp_bounds   = [b for b in all_boundaries if not is_screen(b.name)]
    occurrences   = Counter(b.name for b in all_boundaries)

    logger.info("pipeline: resolved %d CSS class rules from stylesheet", len(rule_map))

    extracted_comps = await extract_all_components(
        sources.js, comp_bounds, occurrences, token_map,
        concurrency=concurrency, rule_map=rule_map,
        on_component_extracted=on_component_extracted,
    )

    screens          = extract_screens(sources.js, all_boundaries)
    screen_bound_map = {b.name: b for b in screen_bounds}
    sem              = asyncio.Semaphore(concurrency)

    async def _extract_sections_for(screen: ExtractedScreen):
        boundary = screen_bound_map.get(screen.name)
        if not boundary:
            return screen.name, []
        async with sem:
            secs = await asyncio.to_thread(extract_sections, sources.js, screen, boundary)
            return screen.name, secs

    section_pairs = await asyncio.gather(*[_extract_sections_for(s) for s in screens])
    sections_map  = dict(section_pairs)

    return extracted_comps, screens, sections_map, tokens


async def _extract_plain_html(
    sources,
    concurrency: int,
) -> tuple[list, list, dict, list]:
    """
    Phases 2–4 for plain_html format.

    Uses html_parser to detect repeating DOM patterns (components) and
    HTML5 semantic elements (sections). No JavaScript boundary detection.
    Returns (extracted_comps, screens, sections_map, tokens).
    """
    from bs4 import BeautifulSoup

    from design_graph.parsing.html_parser import extract_dom_patterns

    tokens = await asyncio.to_thread(extract_tokens, sources)
    soup   = await asyncio.to_thread(BeautifulSoup, sources.inner_html, "html.parser")

    # Components: repeating DOM patterns treated as component definitions
    patterns        = await asyncio.to_thread(extract_dom_patterns, soup)
    extracted_comps = dom_patterns_to_extracted_components(patterns)

    # Synthetic screen: the whole HTML document is one "page"
    screen_name = _html_stem_to_screen_name(sources)
    screen      = ExtractedScreen(
        name=screen_name,
        component_refs=[c.name for c in extracted_comps],
        sections_count=0,
    )

    # Sections: HTML5 semantic elements
    sections     = await asyncio.to_thread(extract_sections_for_plain_html, soup, screen_name)
    sections_map = {screen_name: sections}

    logger.info(
        "plain_html: %d DOM patterns → %d components, %d semantic sections",
        len(patterns), len(extracted_comps), len(sections),
    )
    return extracted_comps, [screen], sections_map, tokens


def _has_react_functions(js: str) -> bool:
    """Return True if the JS string contains PascalCase function definitions."""
    from design_graph.core.patterns import RE_COMP_FN
    return bool(RE_COMP_FN.search(js))


def _html_stem_to_screen_name(sources) -> str:
    """Derive a PascalCase screen name from the HTML content's title or fallback."""
    try:
        from bs4 import BeautifulSoup
        soup  = BeautifulSoup(sources.inner_html, "html.parser")
        title = soup.find("title")
        if title:
            text = title.get_text(strip=True)
            # Convert "My App Title" → "MyAppTitle"
            words = [w.capitalize() for w in text.split() if w.isalnum()]
            if words:
                name = "".join(words[:3])
                if not name.endswith(("Page", "Screen")):
                    name += "Page"
                return name
    except Exception:
        pass
    return "MainPage"


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
