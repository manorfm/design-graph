#!/usr/bin/env python3
"""
query.py — Interface de linha de comando para o grafo de design system.
Usado pelo Makefile para consultas diretas sem o Cursor.

Uso:
  python3 query.py screens
  python3 query.py tokens [color|spacing]
  python3 query.py search <termo>
  python3 query.py inspect <ComponentName>
  python3 query.py impact <ComponentName>
  python3 query.py screen <ScreenName>
"""

import sys, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("GRAPH_DIR", str(Path.home() / "graphs"))
os.environ.setdefault("GRAPH_DB",  str(Path(__file__).parent / "design-graph.db"))

from mcp_server import open_dbs, tool_list_screens, tool_get_tokens, tool_search, \
    tool_get_component, tool_impact, tool_get_screen, tool_get_interactions

def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    conns = open_dbs()
    if not conns:
        print("Nenhum grafo encontrado.")
        print(f"  GRAPH_DIR={os.environ.get('GRAPH_DIR')}")
        print(f"  GRAPH_DB={os.environ.get('GRAPH_DB')}")
        print("Rode: build-graph <prototype.html> --db ~/graphs/nome.db")
        sys.exit(1)

    cmd  = args[0]
    rest = args[1:]
    conn = conns[0][1]

    if cmd == "screens":
        print(tool_list_screens(conns))

    elif cmd == "tokens":
        cat = rest[0] if rest else None
        print(tool_get_tokens(conn, cat))

    elif cmd == "search":
        if not rest:
            print("Uso: python3 query.py search <termo>")
            sys.exit(1)
        print(tool_search(conns, " ".join(rest)))

    elif cmd == "inspect":
        if not rest:
            print("Uso: python3 query.py inspect <ComponentName>")
            sys.exit(1)
        print(tool_get_component(conn, rest[0]))

    elif cmd == "impact":
        if not rest:
            print("Uso: python3 query.py impact <ComponentName>")
            sys.exit(1)
        print(tool_impact(conn, rest[0]))

    elif cmd == "screen":
        if not rest:
            print("Uso: python3 query.py screen <ScreenName>")
            sys.exit(1)
        print(tool_get_screen(conn, rest[0]))

    elif cmd == "interactions":
        if not rest:
            print("Uso: python3 query.py interactions <ComponentName>")
            sys.exit(1)
        print(tool_get_interactions(conn, rest[0]))

    else:
        print(f"Comando desconhecido: {cmd}")
        print(__doc__)
        sys.exit(1)

if __name__ == "__main__":
    main()
