"""
CLI entry point: design-graph

Commands:
  design-graph <proto.html>              — build graph (default)
  design-graph chunk <proto.html>        — export AI-ready chunks as JSONL
  design-graph <proto.html> --diff       — show what changed since last build
  design-graph <proto.html> --force      — rebuild even if HTML is unchanged
  design-graph <proto.html> --db <path>  — save graph to custom path
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from design_graph.extraction.chunker import export_chunks_jsonl
from design_graph.paths import default_db_for


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    if args[0] == "chunk":
        _cmd_chunk(args[1:])
    else:
        _cmd_build(args)


def _cmd_build(args: list[str]) -> None:
    from design_graph.pipeline.coordinator import run_pipeline

    html_path  = Path(args[0])
    show_diff  = "--diff"  in args
    force      = "--force" in args

    db_path: Path
    if "--db" in args:
        db_path = Path(args[args.index("--db") + 1]).expanduser()
    else:
        for a in args[1:]:
            if not a.startswith("--"):
                db_path = Path(a)
                break
        else:
            db_path = default_db_for(html_path.stem)

    state_path = db_path.parent / ".graph-state.json"

    if not html_path.exists():
        print(f"Error: file not found: {html_path}", file=sys.stderr)
        sys.exit(1)

    if force:
        state_path.unlink(missing_ok=True)

    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    stats = asyncio.run(run_pipeline(
        html_path, db_path, state_path,
        show_diff=show_diff, force=force,
    ))

    if stats is None:
        print("Prototype unchanged — skipped. Use --force to rebuild.")
        return

    print(f"\n{'─' * 55}")
    print(f"  Prototype : {html_path.name}")
    print(f"  Graph DB  : {db_path}")
    print(f"{'─' * 55}")
    print(f"  Screens:      {stats.screens:>4}    Sections:   {stats.sections:>4}")
    print(f"  Components:   {stats.components:>4}    Tokens:     {stats.tokens:>4}")
    print(f"  UITexts:      {stats.texts:>4}    Styles:     {stats.styles:>4}")
    print(f"  Interactions: {stats.interactions:>4}    CONTAINS:   {stats.contains_rels:>4}")
    print(f"  Built in {stats.duration_seconds:.2f}s")
    print(f"{'─' * 55}")


def _cmd_chunk(args: list[str]) -> None:
    """Export prototype as AI-ready JSONL chunks without building the graph."""
    from collections import Counter

    from design_graph.extraction.chunker import chunk_extracted_data
    from design_graph.extraction.screen_extractor import extract_screens
    from design_graph.extraction.section_extractor import extract_sections
    from design_graph.parsing.js_parser import find_all_boundaries
    from design_graph.parsing.source_loader import load
    from design_graph.parsing.token_extractor import build_token_map, extract_tokens
    from design_graph.extraction.component_extractor import extract_all_components

    if not args:
        print("Usage: design-graph chunk <prototype.html> [--output chunks.jsonl] [--max-chars 12000]")
        sys.exit(1)

    html_path = Path(args[0])
    output_path = Path(args[args.index("--output") + 1]) if "--output" in args else html_path.with_suffix(".jsonl")
    max_chars = int(args[args.index("--max-chars") + 1]) if "--max-chars" in args else 12_000

    if not html_path.exists():
        print(f"Error: file not found: {html_path}", file=sys.stderr)
        sys.exit(1)

    async def _run():
        sources = await load(html_path)
        bounds  = find_all_boundaries(sources.js)
        tokens  = extract_tokens(sources)
        tm      = build_token_map(tokens)
        occ     = Counter(b.name for b in bounds)
        comps   = await extract_all_components(sources.js, bounds, occ, tm)
        comps_d = {c.name: c for c in comps}
        screens = extract_screens(sources.js, bounds)

        from design_graph.extraction.screen_extractor import is_screen
        from design_graph.parsing.js_parser import find_function_boundaries
        from design_graph.core.patterns import RE_SCREEN_FN
        screen_bounds = {b.name: b for b in find_function_boundaries(sources.js, RE_SCREEN_FN)}

        secs_map = {}
        for screen in screens:
            b = screen_bounds.get(screen.name)
            if b:
                secs_map[screen.name] = extract_sections(sources.js, screen, b)

        chunks = chunk_extracted_data(screens, secs_map, comps_d, max_chars)
        export_chunks_jsonl(chunks, output_path)
        return len(chunks)

    count = asyncio.run(_run())
    print(f"{count} chunks exported → {output_path}")
