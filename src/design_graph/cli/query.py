"""
CLI entry point: design-query

Usage:
  design-query screens
  design-query tokens [color|spacing]
  design-query search <term>
  design-query inspect <ComponentName>
  design-query impact <ComponentName>
  design-query screen <ScreenName>
  design-query interactions <ComponentName>
  design-query children <ComponentName>
"""

from __future__ import annotations

import sys

from design_graph.graph.reader import GraphReader
from design_graph.mcp.tools import ToolDispatcher
from design_graph.paths import resolve_graph_dir


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    readers = _open_readers()
    if not readers:
        print(f"No graphs found in {resolve_graph_dir()}")
        print("Run: design-graph <prototype.html>")
        sys.exit(1)

    dispatcher = ToolDispatcher(readers)
    cmd  = args[0]
    rest = args[1:]
    doc  = readers[0][0]

    reader, _ = dispatcher.pick_reader(doc=doc, active_doc=doc)

    if cmd == "screens":
        print(dispatcher.list_screens())

    elif cmd == "tokens":
        cat = rest[0] if rest else None
        print(dispatcher.get_tokens(reader, cat))

    elif cmd == "search":
        if not rest:
            print("Usage: design-query search <term>")
            sys.exit(1)
        print(dispatcher.tool_search(" ".join(rest)))

    elif cmd == "inspect":
        if not rest:
            print("Usage: design-query inspect <ComponentName>")
            sys.exit(1)
        print(dispatcher.get_component(reader, rest[0]))

    elif cmd == "impact":
        if not rest:
            print("Usage: design-query impact <ComponentName>")
            sys.exit(1)
        print(dispatcher.impact(reader, rest[0]))

    elif cmd == "screen":
        if not rest:
            print("Usage: design-query screen <ScreenName>")
            sys.exit(1)
        print(dispatcher.get_screen(reader, rest[0]))

    elif cmd == "interactions":
        if not rest:
            print("Usage: design-query interactions <ComponentName>")
            sys.exit(1)
        print(dispatcher.get_component_interactions(reader, rest[0]))

    elif cmd == "children":
        if not rest:
            print("Usage: design-query children <ComponentName>")
            sys.exit(1)
        print(dispatcher.get_component_children(reader, rest[0]))

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


def _open_readers() -> list[tuple[str, GraphReader]]:
    import kuzu
    graph_dir = resolve_graph_dir()
    readers = []
    if graph_dir.exists():
        for db_path in sorted(graph_dir.glob("*.db")):
            try:
                db   = kuzu.Database(str(db_path), read_only=True)
                conn = kuzu.Connection(db)
                readers.append((db_path.stem, GraphReader(conn)))
            except Exception:
                pass
    return readers
