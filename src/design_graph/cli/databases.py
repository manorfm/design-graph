"""Database catalog commands for the design-graph CLI."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from design_graph.core.graph_catalog import (
    GraphCatalogError,
    GraphDocumentName,
    GraphMaintenancePlan,
    MaintenanceResult,
)
from design_graph.workspace import GraphWorkspace


@dataclass(frozen=True)
class DatabaseCliArgs:
    action: str
    document: str | None = None
    json_output: bool = False
    force: bool = False
    dry_run: bool = False


class MaintenanceConfirmation(Protocol):
    def approve(self, plan: GraphMaintenancePlan) -> bool: ...


class TerminalMaintenanceConfirmation:
    """Interactive safety boundary for destructive maintenance."""

    def approve(self, plan: GraphMaintenancePlan) -> bool:
        answer = input(f"Delete {len(plan.artifacts)} artifact(s)? [y/N] ").strip().casefold()
        return answer in {"y", "yes"}


def parse_database_args(argv: list[str]) -> DatabaseCliArgs:
    parser = argparse.ArgumentParser(
        prog="design-graph db",
        description="List and select design-graph databases.",
    )
    commands = parser.add_subparsers(dest="action", required=True, metavar="COMMAND")
    list_parser = commands.add_parser("list", help="List available databases")
    list_parser.add_argument("--json", action="store_true", dest="json_output")
    commands.add_parser("current", help="Show the selected database")
    use_parser = commands.add_parser("use", help="Select the default database")
    use_parser.add_argument("document", metavar="NAME")
    info_parser = commands.add_parser("info", help="Show database details")
    info_parser.add_argument("document", metavar="NAME")
    remove_parser = commands.add_parser("remove", help="Remove a database and its owned artifacts")
    remove_parser.add_argument("document", metavar="NAME")
    remove_parser.add_argument("--force", action="store_true", help="Skip confirmation")
    prune_parser = commands.add_parser("prune", help="Remove orphan states and interrupted build data")
    prune_parser.add_argument("--dry-run", action="store_true", help="Show what would be removed")
    prune_parser.add_argument("--force", action="store_true", help="Skip confirmation")
    parsed = parser.parse_args(argv)
    return DatabaseCliArgs(
        action=parsed.action,
        document=getattr(parsed, "document", None),
        json_output=getattr(parsed, "json_output", False),
        force=getattr(parsed, "force", False),
        dry_run=getattr(parsed, "dry_run", False),
    )


def run_database_command(
    args: DatabaseCliArgs,
    confirmation: MaintenanceConfirmation | None = None,
) -> int:
    workspace = GraphWorkspace.open()
    if args.action == "list":
        print(_render_list(workspace, args.json_output))
        return 0
    if args.action in {"remove", "prune"}:
        return _run_maintenance(
            workspace, args,
            confirmation or TerminalMaintenanceConfirmation(),
        )
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


def _run_maintenance(
    workspace: GraphWorkspace,
    args: DatabaseCliArgs,
    confirmation: MaintenanceConfirmation,
) -> int:
    try:
        plan = (
            workspace.catalog.plan_removal(GraphDocumentName(args.document or ""))
            if args.action == "remove"
            else workspace.catalog.plan_prune()
        )
    except (GraphCatalogError, ValueError) as exc:
        print(f"error: {exc}")
        return 1

    print(_render_maintenance_plan(plan))
    if plan.is_empty:
        print("Nothing to remove.")
        return 0
    if args.dry_run:
        print("Dry run: no files were removed.")
        return 0
    if not args.force and not confirmation.approve(plan):
        print("Cancelled.")
        return 0

    try:
        result = workspace.execute_maintenance(plan)
    except OSError as exc:
        print(f"error: could not remove graph artifacts: {exc}")
        print("Stop design-mcp or any process using the database, then retry.")
        return 1
    print(_render_maintenance_result(result))
    return 0


def _render_maintenance_plan(plan: GraphMaintenancePlan) -> str:
    title = f"{plan.operation}: {plan.document.value}" if plan.document else plan.operation
    lines = [title]
    lines.extend(f"  [{artifact.kind.value}] {artifact.path}" for artifact in plan.artifacts)
    return "\n".join(lines)


def _render_maintenance_result(result: MaintenanceResult) -> str:
    return f"Removed {result.removed_count} artifact(s), reclaimed {result.reclaimed_bytes} bytes."


def _render_list(workspace: GraphWorkspace, json_output: bool) -> str:
    default = workspace.configuration.default_document
    rows = [
        {
            "name": database.name.value,
            "path": str(database.path),
            "size_bytes": database.size_bytes,
            "modified_at": _iso_time(database.modified_at),
            "default": default.matches(database.name) if default else False,
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
