"""
CLI entry point: design-graph

Commands:
  design-graph <proto.html>                     build knowledge graph
  design-graph <proto.html> --diff              show what changed since last build
  design-graph <proto.html> --force             rebuild even if HTML is unchanged
  design-graph <proto.html> --db <path>         save graph to a custom path
  design-graph <proto.html> --verbose           show debug-level pipeline logs
  design-graph <proto.html> --quiet             suppress all output except errors
  design-graph chunk <proto.html>               export AI-ready chunks as JSONL
  design-graph chunk <proto.html> --output <f>  write JSONL to custom file
  design-graph chunk <proto.html> --max-chars N set max chars per chunk (default 12000)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

from design_graph.cli._logging import configure_cli_logging
from design_graph.paths import default_db_for


# ── Typed argument containers ─────────────────────────────────────────────────

@dataclass
class BuildCliArgs:
    html_path: Path
    db_path:   Path | None
    show_diff: bool
    force:     bool
    verbose:   bool
    quiet:     bool


@dataclass
class ChunkCliArgs:
    html_path:   Path
    output_path: Path
    max_chars:   int
    verbose:     bool


# ── Argument parsers (pure, testable, no I/O) ─────────────────────────────────

def parse_build_args(argv: list[str]) -> BuildCliArgs:
    """Parse argv for the 'build' command. Raises SystemExit on bad input."""
    p = argparse.ArgumentParser(
        prog="design-graph",
        description="Parse a prototype HTML into a Kuzu design-graph.",
        add_help=True,
    )
    p.add_argument("html_path", type=Path, help="Path to the prototype HTML file")
    p.add_argument("--db",    dest="db_path", type=Path, default=None,
                   metavar="PATH", help="Custom graph database path")
    p.add_argument("--diff",  dest="show_diff", action="store_true",
                   help="Show what changed since the last build")
    p.add_argument("--force", action="store_true",
                   help="Rebuild even if the HTML is unchanged")
    p.add_argument("--verbose", action="store_true",
                   help="Show debug-level pipeline logs")
    p.add_argument("--quiet",   action="store_true",
                   help="Suppress all output except errors")
    ns = p.parse_args(argv)
    return BuildCliArgs(
        html_path=ns.html_path,
        db_path=ns.db_path,
        show_diff=ns.show_diff,
        force=ns.force,
        verbose=ns.verbose,
        quiet=ns.quiet,
    )


def parse_chunk_args(argv: list[str]) -> ChunkCliArgs:
    """Parse argv for the 'chunk' subcommand. Raises SystemExit on bad input."""
    p = argparse.ArgumentParser(
        prog="design-graph chunk",
        description="Export prototype as AI-ready JSONL chunks.",
        add_help=True,
    )
    p.add_argument("html_path", type=Path, help="Path to the prototype HTML file")
    p.add_argument("--output",    dest="output_path", type=Path, default=None,
                   metavar="FILE", help="Output JSONL path (default: <proto>.jsonl)")
    p.add_argument("--max-chars", type=int, default=12_000,
                   metavar="N", help="Maximum characters per chunk (default: 12000)")
    p.add_argument("--verbose", action="store_true",
                   help="Show debug-level logs")
    ns = p.parse_args(argv)
    output_path = ns.output_path or ns.html_path.with_suffix(".jsonl")
    return ChunkCliArgs(
        html_path=ns.html_path,
        output_path=output_path,
        max_chars=ns.max_chars,
        verbose=ns.verbose,
    )


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "chunk":
        _run_chunk(args[1:])
    else:
        _run_build(args)


# ── Command implementations ───────────────────────────────────────────────────

def _run_build(argv: list[str]) -> None:
    from design_graph.pipeline.coordinator import run_pipeline

    try:
        parsed = parse_build_args(argv)
    except SystemExit:
        raise

    configure_cli_logging(verbose=parsed.verbose, quiet=parsed.quiet)

    if not parsed.html_path.exists():
        print(f"error: file not found: {parsed.html_path}", file=sys.stderr)
        sys.exit(1)

    db_path    = parsed.db_path or default_db_for(parsed.html_path.stem)
    state_path = db_path.parent / ".graph-state.json"

    if parsed.force:
        state_path.unlink(missing_ok=True)

    stats = asyncio.run(run_pipeline(
        parsed.html_path, db_path, state_path,
        show_diff=parsed.show_diff,
        force=parsed.force,
    ))

    if stats is None:
        if not parsed.quiet:
            print("Prototype unchanged — skipped. Use --force to rebuild.")
        return

    if not parsed.quiet:
        _print_build_summary(parsed.html_path, db_path, stats)


def _run_chunk(argv: list[str]) -> None:
    from design_graph.extraction.chunker import chunk_extracted_data, export_chunks_jsonl

    try:
        parsed = parse_chunk_args(argv)
    except SystemExit:
        raise

    configure_cli_logging(verbose=parsed.verbose)

    if not parsed.html_path.exists():
        print(f"error: file not found: {parsed.html_path}", file=sys.stderr)
        sys.exit(1)

    count = asyncio.run(_build_and_export_chunks(parsed))
    print(f"{count} chunks exported → {parsed.output_path}")


async def _build_and_export_chunks(parsed: ChunkCliArgs) -> int:
    from collections import Counter

    from design_graph.extraction.chunker import chunk_extracted_data, export_chunks_jsonl
    from design_graph.extraction.component_extractor import extract_all_components
    from design_graph.extraction.screen_extractor import extract_screens
    from design_graph.extraction.section_extractor import extract_sections
    from design_graph.parsing.js_parser import find_all_boundaries, find_function_boundaries
    from design_graph.parsing.source_loader import load
    from design_graph.parsing.token_extractor import build_token_map, extract_tokens
    from design_graph.core.patterns import RE_SCREEN_FN

    sources     = await load(parsed.html_path)
    all_bounds  = find_all_boundaries(sources.js)
    tokens      = extract_tokens(sources)
    token_map   = build_token_map(tokens)
    occurrences = Counter(b.name for b in all_bounds)

    comps   = await extract_all_components(sources.js, all_bounds, occurrences, token_map)
    comps_d = {c.name: c for c in comps}
    screens = extract_screens(sources.js, all_bounds)

    screen_bounds = {b.name: b for b in find_function_boundaries(sources.js, RE_SCREEN_FN)}
    sections_map  = {
        screen.name: extract_sections(sources.js, screen, screen_bounds[screen.name])
        for screen in screens
        if screen.name in screen_bounds
    }

    chunks = chunk_extracted_data(screens, sections_map, comps_d, parsed.max_chars)
    export_chunks_jsonl(chunks, parsed.output_path)
    return len(chunks)


# ── Output formatting ─────────────────────────────────────────────────────────

def _print_build_summary(html_path: Path, db_path: Path, stats) -> None:
    w = 55
    print(f"\n{'─' * w}")
    print(f"  Prototype : {html_path.name}")
    print(f"  Graph DB  : {db_path}")
    print(f"{'─' * w}")
    print(f"  Screens:      {stats.screens:>4}    Sections:   {stats.sections:>4}")
    print(f"  Components:   {stats.components:>4}    Tokens:     {stats.tokens:>4}")
    print(f"  UITexts:      {stats.texts:>4}    Styles:     {stats.styles:>4}")
    print(f"  Interactions: {stats.interactions:>4}    CONTAINS:   {stats.contains_rels:>4}")
    print(f"  Built in {stats.duration_seconds:.2f}s")
    print(f"{'─' * w}")
