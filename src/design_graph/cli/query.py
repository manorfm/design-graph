"""
CLI entry point: design-query

Usage:
  design-query screens
  design-query tokens [color|spacing]
  design-query search <term> [<term>...]
  design-query inspect <ComponentName>
  design-query impact  <ComponentName>
  design-query screen  <ScreenName>
  design-query interactions <ComponentName>
  design-query children <ComponentName>

Options:
  --verbose    Show debug-level logs
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from design_graph.cli._logging import configure_cli_logging
from design_graph.mcp.tools import ToolDispatcher
from design_graph.paths import resolve_graph_dir


# ── Typed argument container ──────────────────────────────────────────────────

@dataclass
class QueryCliArgs:
    command:  str
    name:     str           = ""
    query:    str           = ""
    category: str | None    = None
    verbose:  bool          = False


# ── Argument parser (pure, testable) ──────────────────────────────────────────

def parse_query_args(argv: list[str]) -> QueryCliArgs:
    """
    Parse argv for design-query. Raises SystemExit on bad input or --help.

    --verbose is accepted both before and after the subcommand name by
    using a shared parent parser that each subparser inherits.
    """
    # Shared flags inherited by all subcommands so --verbose can appear
    # either before or after the subcommand keyword.
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--verbose", action="store_true", help="Show debug-level logs")

    p = argparse.ArgumentParser(
        prog="design-query",
        description="Query a design-graph database from the command line.",
        parents=[shared],
        add_help=True,
    )

    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")

    sub.add_parser("screens", parents=[shared], help="List all screens in the graph")

    tok_p = sub.add_parser("tokens", parents=[shared], help="List design tokens")
    tok_p.add_argument("category", nargs="?", default=None,
                       choices=["color", "spacing", "typography", "shadow", "radius"],
                       help="Filter by token category")

    srch_p = sub.add_parser("search", parents=[shared], help="Full-text search across graph")
    srch_p.add_argument("terms", nargs="+", metavar="TERM", help="Search terms")

    for cmd, meta in [
        ("inspect",      "ComponentName"),
        ("impact",       "ComponentName"),
        ("screen",       "ScreenName"),
        ("interactions", "ComponentName"),
        ("children",     "ComponentName"),
    ]:
        sp = sub.add_parser(cmd, parents=[shared], help=f"Query by {meta}")
        sp.add_argument("name", metavar=meta)

    ns = p.parse_args(argv)

    query    = " ".join(ns.terms) if hasattr(ns, "terms") else ""
    name     = getattr(ns, "name", "")
    category = getattr(ns, "category", None)

    return QueryCliArgs(
        command=ns.command,
        name=name,
        query=query,
        category=category,
        verbose=ns.verbose,
    )


# ── Command dispatch (pure, testable — no I/O, takes injected dispatcher) ─────

def dispatch_query_command(
    args: QueryCliArgs,
    dispatcher: "ToolDispatcher",
    reader,
) -> None:
    """
    Route a parsed query command to the correct ToolDispatcher method and
    print the result to stdout.

    Raises SystemExit(1) for unknown commands (should never happen after argparse
    validation, but guards against future additions that forget to add a branch).
    """
    cmd = args.command

    if cmd == "screens":
        print(dispatcher.list_screens())

    elif cmd == "tokens":
        print(dispatcher.get_tokens(reader, args.category))

    elif cmd == "search":
        print(dispatcher.tool_search(args.query))

    elif cmd == "inspect":
        print(dispatcher.get_component(reader, args.name))

    elif cmd == "impact":
        print(dispatcher.impact(reader, args.name))

    elif cmd == "screen":
        print(dispatcher.get_screen(reader, args.name))

    elif cmd == "interactions":
        print(dispatcher.get_component_interactions(reader, args.name))

    elif cmd == "children":
        print(dispatcher.get_component_children(reader, args.name))

    else:
        print(f"error: unknown command '{cmd}'", file=sys.stderr)
        sys.exit(1)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    try:
        args = parse_query_args(sys.argv[1:])
    except SystemExit:
        raise

    configure_cli_logging(verbose=args.verbose)

    readers = _open_all_graph_readers()
    if not readers:
        print(f"No graphs found in {resolve_graph_dir()}", file=sys.stderr)
        print("Run: design-graph <prototype.html>", file=sys.stderr)
        sys.exit(1)

    dispatcher = ToolDispatcher(readers)
    doc        = readers[0][0]
    reader, _  = dispatcher.pick_reader(doc=doc, active_doc=doc)

    dispatch_query_command(args, dispatcher, reader)


# ── Graph reader factory ──────────────────────────────────────────────────────

def _open_all_graph_readers() -> list:
    """
    Discover and open every .db file in the configured graph directory.
    Silently skips databases that fail to open (corrupt, wrong version, etc.)
    and logs a warning so the user can diagnose the problem.
    """
    import logging
    import kuzu
    from design_graph.graph.reader import GraphReader

    logger    = logging.getLogger(__name__)
    graph_dir = resolve_graph_dir()
    readers: list = []

    if not graph_dir.exists():
        return readers

    for db_path in sorted(graph_dir.glob("*.db")):
        try:
            db   = kuzu.Database(str(db_path), read_only=True)
            conn = kuzu.Connection(db)
            readers.append((db_path.stem, GraphReader(conn)))
        except Exception as exc:
            logger.warning("query: failed to open %s: %s", db_path.name, exc)

    return readers
