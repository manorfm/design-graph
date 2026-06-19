"""
CLI entry point: design-graph

Commands:
  design-graph <proto.html>                     build knowledge graph
  design-graph <proto.html> --diff              show what changed since last build
  design-graph <proto.html> --force             rebuild even if HTML is unchanged
  design-graph <proto.html> --db <path>         save graph to a custom path
  design-graph <proto.html> --name <name>       save graph as <name>.db
  design-graph <proto.html> --verbose           show debug-level pipeline logs
  design-graph <proto.html> --quiet             suppress all output except errors
  design-graph --version                        print version and exit
  design-graph chunk <proto.html>               export AI-ready chunks as JSONL
  design-graph chunk <proto.html> --output <f>  write JSONL to custom file
  design-graph chunk <proto.html> --max-chars N set max chars per chunk (default 12000)
  design-graph status                           show graph health and last build info
  design-graph status --db <path>               status for a specific database
  design-graph report                           generate Markdown prototype report
  design-graph report --db <path>               report from a specific database
  design-graph report --output <file>           write report to a Markdown file
  design-graph report --name <name>             override prototype name in report
  design-graph report --no-tokens               exclude design token table
  design-graph report --jsx                     include JSX snippets in report
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

from design_graph.cli._logging import configure_cli_logging
from design_graph.core.graph_catalog import GraphDocumentName
from design_graph.paths import default_db_for
from design_graph.cli.databases import DatabaseCliArgs, parse_database_args


# ── Typed argument containers ─────────────────────────────────────────────────

@dataclass
class BuildCliArgs:
    html_path:   Path
    db_path:     Path | None
    prototype_name: GraphDocumentName | None
    show_diff:   bool
    force:       bool
    verbose:     bool
    quiet:       bool
    json_output: bool = False


@dataclass
class ValidateCliArgs:
    db_path:     Path | None
    verbose:     bool
    json_output: bool
    document:    str | None = None


@dataclass
class ChunkCliArgs:
    html_path:   Path
    output_path: Path
    max_chars:   int
    verbose:     bool


@dataclass
class StatusCliArgs:
    db_path: Path | None
    verbose: bool
    document: str | None = None


@dataclass
class ReportCliArgs:
    db_path:        Path | None
    output_path:    Path | None   # None → write to stdout
    prototype_name: str | None    # None → infer from selected db stem
    include_tokens: bool
    include_jsx:    bool
    verbose:        bool
    document:       str | None = None


# ── Argument parsers (pure, testable, no I/O) ─────────────────────────────────

def parse_status_args(argv: list[str]) -> StatusCliArgs:
    """Parse argv for the 'status' subcommand. Raises SystemExit on bad input."""
    p = argparse.ArgumentParser(
        prog="design-graph status",
        description="Show design-graph database health and last build info.",
        add_help=True,
    )
    p.add_argument("--db",      dest="db_path", type=Path, default=None,
                   metavar="PATH", help="Graph database path")
    p.add_argument("--doc", dest="document", default=None, metavar="NAME",
                   help="Prototype name to inspect")
    p.add_argument("--verbose", action="store_true", help="Show debug-level logs")
    ns = p.parse_args(argv)
    return StatusCliArgs(db_path=ns.db_path, document=ns.document, verbose=ns.verbose)


def parse_build_args(argv: list[str]) -> BuildCliArgs:
    """Parse argv for the 'build' command. Raises SystemExit on bad input."""
    try:
        from importlib.metadata import version as _pkg_version
        _version = _pkg_version("design-graph")
    except Exception:
        _version = "dev"

    p = argparse.ArgumentParser(
        prog="design-graph",
        description="Parse a prototype HTML into a Kuzu design-graph.",
        add_help=True,
    )
    p.add_argument("--version", action="version", version=f"design-graph {_version}")
    p.add_argument("html_path", type=Path, help="Path to the prototype HTML file")
    target = p.add_mutually_exclusive_group()
    target.add_argument("--db", dest="db_path", type=Path, default=None,
                        metavar="PATH", help="Custom graph database path")
    target.add_argument("--name", dest="prototype_name", type=GraphDocumentName, default=None,
                        metavar="NAME", help="Database name to use as the file stem")
    p.add_argument("--diff",  dest="show_diff", action="store_true",
                   help="Show what changed since the last build")
    p.add_argument("--force", action="store_true",
                   help="Rebuild even if the HTML is unchanged")
    p.add_argument("--verbose", action="store_true",
                   help="Show debug-level pipeline logs")
    p.add_argument("--quiet",   action="store_true",
                   help="Suppress all output except errors")
    p.add_argument("--json",    dest="json_output", action="store_true",
                   help="Emit machine-readable JSON to stdout (for CI pipelines)")
    ns = p.parse_args(argv)
    return BuildCliArgs(
        html_path=ns.html_path,
        db_path=ns.db_path,
        prototype_name=ns.prototype_name,
        show_diff=ns.show_diff,
        force=ns.force,
        verbose=ns.verbose,
        quiet=ns.quiet,
        json_output=ns.json_output,
    )


def parse_validate_args(argv: list[str]) -> ValidateCliArgs:
    """Parse argv for the 'validate' subcommand."""
    p = argparse.ArgumentParser(
        prog="design-graph validate",
        description="Validate design-graph database integrity.",
        add_help=True,
    )
    p.add_argument("--db",      dest="db_path", type=Path, default=None,
                   metavar="PATH", help="Graph database path")
    p.add_argument("--doc", dest="document", default=None, metavar="NAME",
                   help="Prototype name to validate")
    p.add_argument("--verbose", action="store_true", help="Show debug-level logs")
    p.add_argument("--json",    dest="json_output", action="store_true",
                   help="Output validation report as JSON")
    ns = p.parse_args(argv)
    return ValidateCliArgs(db_path=ns.db_path, document=ns.document,
                           verbose=ns.verbose, json_output=ns.json_output)


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


def parse_report_args(argv: list[str]) -> ReportCliArgs:
    """Parse argv for the 'report' subcommand. Raises SystemExit on bad input."""
    p = argparse.ArgumentParser(
        prog="design-graph report",
        description="Generate a Markdown prototype report from the design graph.",
        add_help=True,
    )
    p.add_argument("--db",       dest="db_path",        type=Path, default=None,
                   metavar="PATH", help="Graph database path")
    p.add_argument("--doc", dest="document", default=None, metavar="NAME",
                   help="Prototype name to report")
    p.add_argument("--output",   dest="output_path",    type=Path, default=None,
                   metavar="FILE", help="Write report to this Markdown file (default: stdout)")
    p.add_argument("--name",     dest="prototype_name", default=None,
                   metavar="NAME", help="Prototype name shown in the report title")
    p.add_argument("--no-tokens", dest="include_tokens", action="store_false", default=True,
                   help="Exclude the design-token table from the report")
    p.add_argument("--jsx",      dest="include_jsx",    action="store_true",
                   help="Include JSX snippets in component sections")
    p.add_argument("--verbose",  action="store_true",   help="Show debug-level logs")
    ns = p.parse_args(argv)
    return ReportCliArgs(
        db_path=ns.db_path,
        output_path=ns.output_path,
        prototype_name=ns.prototype_name,
        include_tokens=ns.include_tokens,
        include_jsx=ns.include_jsx,
        verbose=ns.verbose,
        document=ns.document,
    )


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]
    if args in (["-h"], ["--help"]):
        _print_main_help()
    elif args and args[0] == "chunk":
        _run_chunk(args[1:])
    elif args and args[0] == "status":
        _run_status(args[1:])
    elif args and args[0] == "validate":
        _run_validate(args[1:])
    elif args and args[0] == "report":
        _run_report(args[1:])
    elif args and args[0] == "db":
        _run_database(args[1:])
    else:
        _run_build(args)


# ── Command implementations ───────────────────────────────────────────────────

def _run_build(argv: list[str]) -> None:
    try:
        parsed = parse_build_args(argv)
    except SystemExit:
        raise

    from design_graph.pipeline.coordinator import run_pipeline

    configure_cli_logging(verbose=parsed.verbose, quiet=parsed.quiet)

    if not parsed.html_path.exists():
        print(f"error: file not found: {parsed.html_path}", file=sys.stderr)
        sys.exit(1)

    db_path = parsed.db_path or default_db_for(parsed.prototype_name or parsed.html_path.stem)
    from design_graph.pipeline.state import BuildStateRepository
    state_repository = BuildStateRepository.for_database(db_path)
    state_path = state_repository.path
    from design_graph.core.graph_catalog import GraphCatalog
    catalog = GraphCatalog.discover(db_path.parent)
    state_repository.migrate_legacy(
        db_path.parent / ".graph-state.json",
        known_databases=tuple(database.path for database in catalog.databases),
    )

    previous_state = state_repository.load()
    source_changed = bool(
        previous_state.source_path
        and Path(previous_state.source_path).resolve() != parsed.html_path.resolve()
    )
    if source_changed:
        print(
            f"warning: {db_path.name} was previously built from {previous_state.source_path}; "
            f"it will be replaced with {parsed.html_path}",
            file=sys.stderr,
        )

    effective_force = parsed.force or source_changed
    if effective_force:
        state_repository.clear()

    from design_graph.pipeline.build_progress import SilentBuildReporter, TerminalBuildReporter
    reporter = (
        SilentBuildReporter()
        if parsed.quiet or parsed.json_output
        else TerminalBuildReporter()
    )

    stats = asyncio.run(run_pipeline(
        parsed.html_path, db_path, state_path,
        show_diff=parsed.show_diff,
        force=effective_force,
        reporter=reporter,
    ))

    if stats is None:
        if parsed.json_output:
            import json as _json
            print(_json.dumps({"status": "skipped", "reason": "unchanged"}))
        elif not parsed.quiet:
            print("Prototype unchanged — skipped. Use --force to rebuild.")
        return

    if parsed.json_output:
        import json as _json
        print(_json.dumps({
            "status":           "built",
            "screens":          stats.screens,
            "components":       stats.components,
            "tokens":           stats.tokens,
            "sections":         stats.sections,
            "interactions":     stats.interactions,
            "styles":           stats.styles,
            "texts":            stats.texts,
            "contains_rels":    stats.contains_rels,
            "component_props":  stats.component_props,
            "section_styles":   stats.section_styles,
            "duration_seconds": round(stats.duration_seconds, 3),
        }))
    elif not parsed.quiet:
        _print_build_summary(parsed.html_path, db_path, stats)


def _print_main_help() -> None:
    """Print the complete command overview without importing pipeline dependencies."""
    parser = argparse.ArgumentParser(
        prog="design-graph",
        description="Parse prototype HTML into a Kuzu design graph.",
        usage="design-graph [--version] <html_path> [build options]\n"
              "       design-graph COMMAND [options]",
        epilog=(
            "commands:\n"
            "  chunk     Export prototype content as AI-ready JSONL chunks\n"
            "  status    Show database health and last build information\n"
            "  validate  Validate database integrity (supports JSON output)\n"
            "  report    Generate a Markdown prototype report\n"
            "  db        List, inspect and select graph databases\n\n"
            "build options:\n"
            "  --db PATH    Write to a custom database path\n"
            "  --name NAME  Write to <name>.db under the graph directory\n"
            "  --diff       Show changes since the previous build\n"
            "  --force      Rebuild even when the HTML is unchanged\n"
            "  --verbose    Show debug-level logs\n"
            "  --quiet      Suppress output except errors\n"
            "  --json       Emit machine-readable build output\n\n"
            "Run 'design-graph COMMAND --help' for command-specific options."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="help", help="Show this help message and exit")
    parser.add_argument("--version", action="store_true", help="Show version and exit")
    parser.parse_args(["--help"])


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
    from design_graph.extraction.chunker import chunk_extracted_data, export_chunks_jsonl
    from design_graph.parsing.format_detector import PLAIN_HTML
    from design_graph.parsing.source_loader import load

    sources = await load(parsed.html_path)

    from design_graph.pipeline.coordinator import _has_react_functions

    if sources.format == PLAIN_HTML and not _has_react_functions(sources.js):
        comps_d, screens, sections_map = await _extract_chunks_plain_html(sources)
    else:
        comps_d, screens, sections_map = await _extract_chunks_react(sources)

    chunks = chunk_extracted_data(screens, sections_map, comps_d, parsed.max_chars)
    export_chunks_jsonl(chunks, parsed.output_path)
    return len(chunks)


async def _extract_chunks_react(sources) -> tuple[dict, list, dict]:
    """Extract chunk data from a React/bundled prototype."""
    from collections import Counter

    from design_graph.extraction.component_extractor import extract_all_components, select_renderable_boundaries
    from design_graph.extraction.screen_extractor import extract_screens
    from design_graph.extraction.section_extractor import extract_sections
    from design_graph.parsing.js_parser import find_all_boundaries, find_function_boundaries
    from design_graph.parsing.token_extractor import build_token_map, extract_tokens
    from design_graph.core.patterns import RE_SCREEN_FN

    all_bounds  = select_renderable_boundaries(sources.js, find_all_boundaries(sources.js))
    tokens      = extract_tokens(sources)
    token_map   = build_token_map(tokens)
    occurrences = Counter(b.name for b in all_bounds)

    comps        = await extract_all_components(sources.js, all_bounds, occurrences, token_map)
    comps_d      = {c.name: c for c in comps}
    screens      = extract_screens(sources.js, all_bounds)
    screen_bounds = {b.name: b for b in find_function_boundaries(sources.js, RE_SCREEN_FN)}
    sections_map = {
        screen.name: extract_sections(sources.js, screen, screen_bounds[screen.name])
        for screen in screens
        if screen.name in screen_bounds
    }
    return comps_d, screens, sections_map


async def _extract_chunks_plain_html(sources) -> tuple[dict, list, dict]:
    """Extract chunk data from a plain HTML prototype."""
    import asyncio
    from bs4 import BeautifulSoup

    from design_graph.core.models import ExtractedScreen
    from design_graph.extraction.plain_html_component_extractor import (
        dom_patterns_to_extracted_components,
    )
    from design_graph.extraction.section_extractor import extract_sections_for_plain_html
    from design_graph.parsing.html_parser import extract_dom_patterns
    from design_graph.pipeline.coordinator import _html_stem_to_screen_name

    soup     = await asyncio.to_thread(BeautifulSoup, sources.inner_html, "html.parser")
    patterns = await asyncio.to_thread(extract_dom_patterns, soup)
    comps    = dom_patterns_to_extracted_components(patterns)
    comps_d  = {c.name: c for c in comps}

    screen_name = _html_stem_to_screen_name(sources)
    screen      = ExtractedScreen(
        name=screen_name,
        component_refs=[c.name for c in comps],
        sections_count=0,
    )
    sections     = await asyncio.to_thread(extract_sections_for_plain_html, soup, screen_name)
    sections_map = {screen_name: sections}
    return comps_d, [screen], sections_map


def _run_validate(argv: list[str]) -> None:
    import json as _json
    from design_graph.cli.validate import render_validation_report, validate_graph

    try:
        parsed = parse_validate_args(argv)
    except SystemExit:
        raise

    configure_cli_logging(verbose=parsed.verbose)

    db_path = _select_database(parsed.db_path, parsed.document)
    report  = validate_graph(db_path)

    if parsed.json_output:
        print(_json.dumps(report.to_dict(), indent=2))
    else:
        print(render_validation_report(report))

    if report.status == "errors":
        sys.exit(1)


def _run_status(argv: list[str]) -> None:
    from design_graph.cli.status import collect_graph_status, render_status_report

    try:
        parsed = parse_status_args(argv)
    except SystemExit:
        raise

    configure_cli_logging(verbose=parsed.verbose)

    from design_graph.workspace import GraphWorkspace
    workspace = GraphWorkspace.open()
    if workspace.catalog.databases or parsed.db_path or parsed.document:
        selected = _select_graph(parsed.db_path, parsed.document)
        db_path = selected.database.path
        selection_source = selected.source.value
    else:
        db_path = workspace.catalog.directory / "design-graph.db"
        selection_source = "empty workspace"
    from design_graph.pipeline.state import BuildStateRepository
    state_path = BuildStateRepository.for_database(db_path).path

    report = collect_graph_status(
        db_path=db_path, state_path=state_path,
        selection_source=selection_source,
    )
    print(render_status_report(report))


def _run_report(argv: list[str]) -> None:
    try:
        parsed = parse_report_args(argv)
    except SystemExit:
        raise

    configure_cli_logging(verbose=parsed.verbose)

    db_path        = _select_database(parsed.db_path, parsed.document)
    prototype_name = parsed.prototype_name or db_path.stem

    report = _build_report_from_graph(db_path, prototype_name, parsed)
    _emit_report(report, parsed.output_path)


def _build_report_from_graph(
    db_path: Path,
    prototype_name: str,
    parsed: ReportCliArgs,
):
    """Open db_path read-only and build a PrototypeReport. All graph imports are local (G9)."""
    import kuzu

    from design_graph.cli.report import ReportConfig, build_prototype_report
    from design_graph.graph.reader import GraphReader

    config = ReportConfig(
        prototype_name=prototype_name,
        include_tokens=parsed.include_tokens,
        include_jsx=parsed.include_jsx,
    )
    db     = kuzu.Database(str(db_path), read_only=True)
    conn   = kuzu.Connection(db)
    reader = GraphReader(conn)
    return build_prototype_report(reader, config)


def _emit_report(report, output_path: Path | None) -> None:
    """Render report to Markdown and write to output_path or print to stdout."""
    from design_graph.cli.report import render_markdown_report

    md = render_markdown_report(report)

    if output_path:
        output_path.write_text(md, encoding="utf-8")
        print(f"Report written to {output_path}")
    else:
        print(md)


def _auto_detect_db() -> Path:
    """Compatibility entry point with deterministic, ambiguity-safe selection."""
    from design_graph.workspace import GraphWorkspace
    workspace = GraphWorkspace.open()
    if not workspace.catalog.databases:
        return workspace.catalog.directory / "design-graph.db"
    return _select_database(None, None)


def _select_database(db_path: Path | None, document: str | None) -> Path:
    return _select_graph(db_path, document).database.path


def _select_graph(db_path: Path | None, document: str | None):
    from design_graph.core.graph_catalog import GraphCatalogError
    from design_graph.workspace import GraphWorkspace
    try:
        return GraphWorkspace.open().select(db_path=db_path, document=document)
    except GraphCatalogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def _run_database(argv: list[str]) -> None:
    from design_graph.cli.databases import run_database_command
    exit_code = run_database_command(parse_database_args(argv))
    if exit_code:
        raise SystemExit(exit_code)


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
    print(f"  Props:        {stats.component_props:>4}    SecStyles:  {stats.section_styles:>4}")
    print(f"  Built in {stats.duration_seconds:.2f}s")
    print(f"{'─' * w}")
