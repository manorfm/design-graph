"""
MCP server for design-graph, backed by the official `mcp` SDK.

MCPServer owns tool dispatch and session state (active prototype, loaded
readers, reload-on-staleness) as plain dicts/strings — it has no dependency
on `mcp` SDK types. The SDK is wired to it only at the bottom of this module
(_to_sdk_tool, _build_sdk_server, run_stdio), the one place that imports
`mcp`. That keeps MCPServer trivially testable, and the wire protocol (JSON-RPC
framing, version negotiation, notifications) entirely the SDK's problem.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from design_graph.graph.reader import GraphReader

try:
    from importlib.metadata import version as _pkg_version
    _VERSION = _pkg_version("design-graph")
except Exception:
    _VERSION = "dev"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GraphDirectorySnapshot:
    """
    The on-disk state of a graph directory's *.db files at one point in time.

    Two snapshots compare equal only when every path and its mtime match —
    that's what tells MCPServer a rebuild happened since it last loaded,
    without either side needing to know *what* changed.
    """

    mtime_by_path: dict[Path, float]

    @classmethod
    def of(cls, graph_dir: Path | None) -> GraphDirectorySnapshot:
        if graph_dir is None or not graph_dir.exists():
            return cls({})
        return cls({p: p.stat().st_mtime for p in graph_dir.glob("*.db")})

    def has_changed_since(self, previous: GraphDirectorySnapshot) -> bool:
        return self.mtime_by_path != previous.mtime_by_path


def _load_readers(graph_dir: Path) -> list[tuple[str, GraphReader]]:
    """Open one read-only GraphReader per *.db file in graph_dir."""
    if not graph_dir.exists():
        return []

    import kuzu

    from design_graph.graph.reader import GraphReader

    readers: list[tuple[str, GraphReader]] = []
    for db_path in sorted(graph_dir.glob("*.db")):
        try:
            db = kuzu.Database(str(db_path), read_only=True)
            readers.append((db_path.stem, GraphReader(kuzu.Connection(db))))
            sys.stderr.write(f"[design-graph] loaded: {db_path.name}\n")
        except Exception as exc:
            sys.stderr.write(f"[design-graph] failed to open {db_path.name}: {exc}\n")
    return readers


def _warn_if_no_graphs(readers: list, graph_dir: Path) -> None:
    if readers:
        return
    sys.stderr.write(
        f"[design-graph] no graphs found in {graph_dir}\n"
        "  Run: design-graph <prototype.html>\n"
    )


@dataclass(frozen=True)
class ToolCallResult:
    """
    The outcome of one dispatched tool call: the Markdown text a client
    should show, and whether it represents a genuine execution failure —
    MCP's isError, distinct from a protocol-level error. Carrying both facts
    on one value means the SDK-wiring boundary never has to guess which text
    strings mean "this call failed."
    """

    text: str
    is_error: bool = False


class MCPServer:
    """
    Tool dispatch and session state for the design-graph MCP server.

    No `mcp` SDK dependency: tool_definitions() and dispatch_tool_call() work
    over plain dicts/strings, so this class is unit-testable without a
    protocol layer and stays reusable if that layer ever changes again.
    """

    def __init__(
        self, readers: list[tuple[str, GraphReader]], graph_dir: Path | None = None
    ) -> None:
        from design_graph.mcp.tools import ToolDispatcher
        from design_graph.paths import load_user_config

        self._graph_dir  = graph_dir
        self._readers    = readers
        self._dispatcher = ToolDispatcher(readers)
        self._snapshot   = GraphDirectorySnapshot.of(graph_dir)
        configured = str(load_user_config().get("default_doc", "")).strip()
        self._active_doc: str = os.environ.get("DESIGN_GRAPH_DOC", "").strip() or configured

    def tool_definitions(self) -> list[dict]:
        from design_graph.mcp.tools import TOOL_DEFINITIONS
        return TOOL_DEFINITIONS

    def startup_description(self) -> str:
        """A short line describing what's loaded, shown at initialize time."""
        doc_names = [n for n, _ in self._readers]
        if not doc_names:
            return "No graphs loaded. Run 'design-graph <prototype.html>' to build one."
        if len(doc_names) == 1 or self._active_doc:
            active = self._active_doc or doc_names[0]
            return (
                f"Active prototype: '{active}'. "
                "Use list_screens to explore, get_component for components."
            )
        return (
            f"Loaded: {', '.join(f'{chr(39)}{n}{chr(39)}' for n in doc_names)}. "
            "Call set_prototype(name='...') to select one."
        )

    def dispatch_tool_call(self, name: str, arguments: dict) -> ToolCallResult:
        self._reload_if_stale()

        if name == "set_prototype":
            return ToolCallResult(text=self._set_prototype(arguments.get("name", "")))

        try:
            text = self._dispatcher.dispatch(name, arguments, self._active_doc)
        except Exception as exc:
            sys.stderr.write(f"[design-graph] ERROR {name}: {traceback.format_exc()}\n")
            return ToolCallResult(text=f"Error executing {name}: {exc}", is_error=True)

        sys.stderr.write(f"[design-graph] {name} → {len(text)} chars\n")
        return ToolCallResult(text=text)

    def _reload_if_stale(self) -> None:
        """
        Reopen every *.db file when the graph directory changed since load.

        Kuzu read-only connections don't see writes made by another process
        after they're opened, so a prototype rebuilt while this session is
        already running would otherwise stay invisible until it restarts.
        """
        current = GraphDirectorySnapshot.of(self._graph_dir)
        if not current.has_changed_since(self._snapshot):
            return

        from design_graph.mcp.tools import ToolDispatcher

        self._readers    = _load_readers(self._graph_dir)
        self._dispatcher = ToolDispatcher(self._readers)
        self._snapshot   = current
        logger.info(
            "mcp-server: graph directory changed — reloaded %d prototype(s)",
            len(self._readers),
        )

    def _set_prototype(self, name: str) -> str:
        if not name:
            if self._active_doc:
                return f"Active prototype: '{self._active_doc}'"
            if len(self._readers) == 1:
                return f"Auto-selected: '{self._readers[0][0]}' (only one prototype loaded)"
            names = ", ".join(f"'{n}'" for n, _ in self._readers)
            return f"No active prototype set.\nAvailable: {names}"

        for doc_name, _ in self._readers:
            if doc_name.lower() == name.lower() or name.lower() in doc_name.lower():
                self._active_doc = doc_name
                sys.stderr.write(f"[design-graph] active prototype → '{doc_name}'\n")
                return f"Active prototype set to '{doc_name}'."

        available = ", ".join(f"'{n}'" for n, _ in self._readers)
        return f"Prototype '{name}' not found.\nAvailable: {available}"


# ── mcp SDK wiring ─────────────────────────────────────────────────────────────
# Only this section imports `mcp`. It translates MCPServer's plain
# dicts/strings into SDK types and back — MCPServer itself never sees them.

def _to_sdk_tool(definition: dict):
    from mcp import types

    return types.Tool(
        name=definition["name"],
        description=definition["description"],
        input_schema=definition["inputSchema"],
        annotations=types.ToolAnnotations(read_only_hint=True),
    )


def _build_sdk_server(mcp_server: MCPServer):
    from mcp import types
    from mcp.server.lowlevel import Server

    async def on_list_tools(ctx, params):
        return types.ListToolsResult(
            tools=[_to_sdk_tool(t) for t in mcp_server.tool_definitions()]
        )

    async def on_call_tool(ctx, params):
        result = mcp_server.dispatch_tool_call(params.name, params.arguments or {})
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=result.text)],
            is_error=result.is_error,
        )

    return Server(
        "design-graph",
        version=_VERSION,
        description=mcp_server.startup_description(),
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


async def run_stdio(mcp_server: MCPServer) -> None:
    from mcp.server.stdio import stdio_server

    sdk_server = _build_sdk_server(mcp_server)
    async with stdio_server() as (read_stream, write_stream):
        await sdk_server.run(
            read_stream, write_stream, sdk_server.create_initialization_options()
        )


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    """Open graph databases and start the MCP server."""
    parser = argparse.ArgumentParser(
        prog="design-mcp",
        description="Serve design-graph databases over MCP using the official SDK.",
    )
    parser.add_argument("--version", action="version", version=f"design-mcp {_VERSION}")
    # MCP hosts may append client-specific arguments; only this server's own
    # help/version flags are relevant and unknown host arguments are ignored.
    parser.parse_known_args()

    from design_graph.paths import resolve_graph_dir

    graph_dir = resolve_graph_dir()
    readers = _load_readers(graph_dir)
    _warn_if_no_graphs(readers, graph_dir)

    asyncio.run(run_stdio(MCPServer(readers, graph_dir)))
