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
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from design_graph.cli._logging import configure_cli_logging
from design_graph.paths import resolve_graph_dir

if TYPE_CHECKING:
    from design_graph.mcp.tools import ToolDispatcher


# ── Typed argument container ──────────────────────────────────────────────────

@dataclass
class QueryCliArgs:
    command:  str
    name:     str           = ""
    query:    str           = ""
    category: str | None    = None
    verbose:  bool          = False
    document: str | None    = None
    db_path:  Path | None   = None


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
    shared.add_argument("--verbose", action="store_true", default=argparse.SUPPRESS,
                        help="Show debug-level logs")
    shared.add_argument("--doc", dest="document", metavar="NAME", default=argparse.SUPPRESS,
                        help="Prototype name")
    shared.add_argument("--db", dest="db_path", type=Path, metavar="PATH",
                        default=argparse.SUPPRESS, help="Graph database path")

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
        verbose=getattr(ns, "verbose", False),
        document=getattr(ns, "document", None),
        db_path=getattr(ns, "db_path", None),
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

    from design_graph.mcp.tools import ToolDispatcher

    from design_graph.core.graph_catalog import GraphCatalogError
    from design_graph.workspace import GraphWorkspace
    try:
        selected = GraphWorkspace.open().select(db_path=args.db_path, document=args.document)
    except GraphCatalogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
    readers = _open_graph_reader(selected.database.path)
    if not readers:
        print(f"No graphs found in {resolve_graph_dir()}", file=sys.stderr)
        print("Run: design-graph <prototype.html>", file=sys.stderr)
        sys.exit(1)

    dispatcher = ToolDispatcher(readers)
    doc        = readers[0][0]
    reader, _  = dispatcher.pick_reader(doc=doc, active_doc=doc)

    dispatch_query_command(args, dispatcher, reader)


def _open_graph_reader(db_path: Path) -> list:
    import kuzu
    from design_graph.graph.reader import GraphReader
    try:
        db = kuzu.Database(str(db_path), read_only=True)
        return [(db_path.stem, GraphReader(kuzu.Connection(db)))]
    except Exception:
        return []
