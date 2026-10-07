"""The README's schema diagram is generated from the schema's DDL, so it can never drift from it."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3] / "scripts"))
from schema_diagram import mermaid, updated_readme  # noqa: E402

from design_graph.model.graph.schema import node_tables, rel_tables  # noqa: E402

README = Path(__file__).parents[3] / "README.md"


def test_every_node_with_its_columns_and_key_is_drawn():
    diagram = mermaid()
    assert diagram.startswith("```mermaid\nerDiagram\n")
    for name, table in node_tables().items():
        assert f'    n_{name}["{name}"] {{\n' in diagram
        assert f"        {table.columns[table.key]} {table.key} PK\n" in diagram


def test_every_relationship_is_drawn_between_its_endpoints():
    diagram = mermaid()
    for name, rel in rel_tables().items():
        assert f"    n_{rel.source} ||--o{{ n_{rel.target} : {name}\n" in diagram


def test_the_readme_carries_the_current_diagram():
    text = README.read_text(encoding="utf-8")
    assert "<!-- schema:begin -->" in text and updated_readme(text) == text


def test_the_diagram_replaces_whatever_sits_between_its_markers():
    text = "a\n<!-- schema:begin -->\nold\n<!-- schema:end -->\nb\n"
    assert updated_readme(text) == f"a\n<!-- schema:begin -->\n{mermaid()}<!-- schema:end -->\nb\n"
