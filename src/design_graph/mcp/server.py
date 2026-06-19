"""
MCP server — JSON-RPC 2.0 over stdio.

Responsibilities: protocol loop only.
All tool logic lives in tools.py; all DB access lives in graph/reader.py.
The only mutable state here is _active_doc (changed via set_prototype).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from design_graph.graph.reader import GraphReader

try:
    from importlib.metadata import version as _pkg_version
    _VERSION = _pkg_version("design-graph")
except Exception:
    _VERSION = "dev"

logger = logging.getLogger(__name__)


class MCPServer:
    """JSON-RPC 2.0 server. Reads from stdin, writes to stdout."""

    def __init__(self, readers: list[tuple[str, GraphReader]]) -> None:
        from design_graph.mcp.tools import ToolDispatcher

        self._readers    = readers
        self._dispatcher = ToolDispatcher(readers)
        self._active_doc: str = os.environ.get("DESIGN_GRAPH_DOC", "").strip()

    def run(self) -> None:
        """Main event loop — blocks until stdin closes."""
        logger.info("mcp-server: started (version=%s, prototypes=%d)", _VERSION, len(self._readers))
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            response = self.handle(msg)
            if response is not None:
                self._send(response)

    def handle(self, msg: dict) -> dict | None:
        method = msg.get("method", "")
        mid    = msg.get("id")
        params = msg.get("params", {})

        if method == "initialize":
            return self._handle_initialize(mid)

        if method in ("notifications/initialized", "initialized"):
            return None

        if method == "tools/list":
            from design_graph.mcp.tools import TOOL_DEFINITIONS

            return {"jsonrpc": "2.0", "id": mid,
                    "result": {"tools": TOOL_DEFINITIONS}}

        if method == "tools/call":
            return self._handle_tool_call(mid, params)

        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32601, "message": f"Method not found: {method}"}}

    # ── Protocol handlers ────────────────────────────────────────────────────

    def _handle_initialize(self, mid) -> dict:
        doc_names = [n for n, _ in self._readers]
        if not doc_names:
            description = (
                "No graphs loaded. Run 'design-graph <prototype.html>' to build one."
            )
        elif len(doc_names) == 1 or self._active_doc:
            active = self._active_doc or doc_names[0]
            description = (
                f"Active prototype: '{active}'. "
                "Use list_screens to explore, get_component for components."
            )
        else:
            description = (
                f"Loaded: {', '.join(f'{chr(39)}{n}{chr(39)}' for n in doc_names)}. "
                "Call set_prototype(name='...') to select one."
            )

        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities":    {"tools": {}},
                "serverInfo":      {"name": "design-graph", "version": _VERSION,
                                    "description": description},
            },
        }

    def _handle_tool_call(self, mid, params: dict) -> dict:
        tool_name = params.get("name", "")
        args      = params.get("arguments", {})

        if tool_name == "set_prototype":
            text = self._set_prototype(args.get("name", ""))
            return {"jsonrpc": "2.0", "id": mid,
                    "result": {"content": [{"type": "text", "text": text}]}}

        try:
            text = self._dispatcher.dispatch(tool_name, args, self._active_doc)
            sys.stderr.write(f"[design-graph] {tool_name} → {len(text)} chars\n")
        except Exception as exc:
            import traceback
            tb = traceback.format_exc()
            sys.stderr.write(f"[design-graph] ERROR {tool_name}: {tb}\n")
            text = f"Error executing {tool_name}:\n{tb}"

        return {"jsonrpc": "2.0", "id": mid,
                "result": {"content": [{"type": "text", "text": text}]}}

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

    @staticmethod
    def _send(obj: dict) -> None:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    """Open graph databases and start the MCP server."""
    parser = argparse.ArgumentParser(
        prog="design-mcp",
        description="Serve design-graph databases over MCP using JSON-RPC 2.0 on stdio.",
    )
    parser.add_argument("--version", action="version", version=f"design-mcp {_VERSION}")
    # MCP hosts may append client-specific arguments; only this server's own
    # help/version flags are relevant and unknown host arguments are ignored.
    parser.parse_known_args()

    from design_graph.graph.reader import GraphReader
    from design_graph.paths import resolve_graph_dir

    graph_dir = resolve_graph_dir()
    readers: list[tuple[str, GraphReader]] = []

    if graph_dir.exists():
        import kuzu
        for db_path in sorted(graph_dir.glob("*.db")):
            try:
                db   = kuzu.Database(str(db_path), read_only=True)
                conn = kuzu.Connection(db)
                readers.append((db_path.stem, GraphReader(conn)))
                sys.stderr.write(f"[design-graph] loaded: {db_path.name}\n")
            except Exception as exc:
                sys.stderr.write(f"[design-graph] failed to open {db_path.name}: {exc}\n")

    if not readers:
        sys.stderr.write(
            f"[design-graph] no graphs found in {graph_dir}\n"
            "  Run: design-graph <prototype.html>\n"
        )

    MCPServer(readers).run()
