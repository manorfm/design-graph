"""Database catalog commands for the design-graph CLI."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from design_graph.core.graph_catalog import GraphCatalogError, GraphDocumentName
from design_graph.workspace import GraphWorkspace


@dataclass(frozen=True)
class DatabaseCliArgs:
    action: str
    document: str | None = None
    json_output: bool = False


def parse_database_args(argv: list[str]) -> DatabaseCliArgs:
    parser = argparse.ArgumentParser(
        prog="design-graph db",
        description="List and select design-graph databases.",
    )
    commands = parser.add_subparsers(dest="action", required=True, metavar="COMMAND")
    list_parser = commands.add_parser("list", help="List available databases")
    list_parser.add_argument("--json", action="store_true", dest="json_output")
    commands.add_parser("current", help="Show the selected database")
    for action in ("use", "info"):
        command = commands.add_parser(action, help=f"{action.title()} a database")
        command.add_argument("document", metavar="NAME")
    parsed = parser.parse_args(argv)
    return DatabaseCliArgs(
        action=parsed.action,
        document=getattr(parsed, "document", None),
        json_output=getattr(parsed, "json_output", False),
    )


def run_database_command(args: DatabaseCliArgs) -> int:
    workspace = GraphWorkspace.open()
    if args.action == "list":
        print(_render_list(workspace, args.json_output))
        return 0
    try:
        selected = (
            workspace.set_default(args.document or "")
            if args.action == "use"
            else workspace.select(document=args.document)
        )
    except GraphCatalogError as exc:
        print(f"error: {exc}")
        return 1
    if args.action == "current":
        print(f"{selected.database.name.value} ({selected.source.value})")
    elif args.action == "use":
        print(f"Default prototype set to '{selected.database.name.value}'.")
    else:
        database = selected.database
        print(f"Name     : {database.name.value}")
        print(f"Path     : {database.path}")
        print(f"Size     : {database.size_bytes} bytes")
        print(f"Modified : {_iso_time(database.modified_at)}")
        print(f"State    : {database.state_path}")
    return 0


def _render_list(workspace: GraphWorkspace, json_output: bool) -> str:
    default = workspace.configuration.get("default_doc", "")
    rows = [
        {
            "name": database.name.value,
            "path": str(database.path),
            "size_bytes": database.size_bytes,
            "modified_at": _iso_time(database.modified_at),
            "default": GraphDocumentName(default).matches(database.name) if default else False,
        }
        for database in workspace.catalog.databases
    ]
    if json_output:
        return json.dumps(rows, indent=2)
    if not rows:
        return f"No graph databases found in {workspace.catalog.directory}"
    lines = ["NAME\tSIZE\tUPDATED\tDEFAULT"]
    for row in rows:
        lines.append(
            f"{row['name']}\t{row['size_bytes']}\t{row['modified_at']}\t"
            f"{'*' if row['default'] else ''}"
        )
    return "\n".join(lines)


def _iso_time(timestamp: float) -> str:
    if not timestamp:
        return "unknown"
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()

