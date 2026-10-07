#!/usr/bin/env python3
"""
The graph schema as a Mermaid ER diagram, generated from the DDL in
design_graph.model.graph.schema — the one place the schema is declared —
and kept in the README between `<!-- schema:begin -->` and
`<!-- schema:end -->`.

usage: python scripts/schema_diagram.py [--write]   (prints the diagram, or rewrites the README's)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from design_graph.model.graph.schema import node_tables, rel_tables

README = Path(__file__).resolve().parents[1] / "README.md"
_RE_BLOCK = re.compile(r"(<!-- schema:begin -->\n).*?(<!-- schema:end -->)", re.DOTALL)


def mermaid() -> str:
    """Every node table with its columns (key marked PK) and every relationship between its endpoints."""
    lines = ["```mermaid", "erDiagram"]
    for name, table in node_tables().items():
        lines.append(f'    {_entity(name)}["{name}"] {{')
        lines += [
            f"        {kind} {column}{' PK' if column == table.key else ''}"
            for column, kind in table.columns.items()
        ]
        lines.append("    }")
    lines += [
        f"    {_entity(rel.source)} ||--o{{ {_entity(rel.target)} : {name}" for name, rel in rel_tables().items()
    ]
    return "\n".join(lines + ["```"]) + "\n"


def _entity(table: str) -> str:
    """A node table's id in the diagram — prefixed, since Mermaid reserves words like `style`; its label is the name."""
    return f"n_{table}"


def updated_readme(text: str) -> str:
    """The README with the diagram between its markers replaced by the current one."""
    return _RE_BLOCK.sub(lambda match: f"{match.group(1)}{mermaid()}{match.group(2)}", text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--write", action="store_true", help="rewrite the diagram in README.md")
    args = parser.parse_args(argv)
    if not args.write:
        sys.stdout.write(mermaid())
        return 0
    README.write_text(updated_readme(README.read_text(encoding="utf-8")), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
