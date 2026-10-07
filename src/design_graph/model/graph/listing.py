"""
Listings of everything a prototype's graph holds — sections, props, sources,
actions — for search, and each component's or screen's actions. Mixed into
GraphReader, whose queries it uses.
"""

from __future__ import annotations

from collections import defaultdict


class CatalogQueries:
    """GraphReader's catalog and action queries (relies on its _q)."""

    def actions_of(self, kind: str, name: str) -> list[dict]:
        """A component's or screen's actions, in the order its source declares them."""
        relation = "HAS_ACTION" if kind == "Component" else "SCREEN_HAS_ACTION"
        return self._q(
            f"MATCH (n:{kind} {{name:$n}})-[r:{relation}]->(a:Action) "
            "RETURN a.trigger AS trigger, a.element AS element, a.handler AS handler, a.effect AS effect "
            "ORDER BY offset(ID(r))",
            {"n": name},
        )

    def list_sections(self) -> list[dict]:
        """Every section, with the screen it belongs to — so a section id can be shown as "Tela › Seção"."""
        return self._q("MATCH (sec:Section) RETURN sec.id AS id, sec.screen AS screen, sec.name AS name")

    def list_props(self) -> list[dict]:
        """Every declared prop, with its component."""
        return self._q(
            "MATCH (c:Component)-[:HAS_PROP]->(p:ComponentProp) RETURN c.name AS component, p.prop_name AS prop"
        )

    def list_actions(self) -> list[dict]:
        """Every action, with the component or screen it belongs to."""
        return self._q(
            "MATCH (a:Action) RETURN a.owner AS owner, a.trigger AS trigger, a.element AS element, "
            "a.handler AS handler, a.effect AS effect"
        )

    def list_sources(self) -> list[dict]:
        """Every component's and screen's own source, for searching what the code names."""
        return [
            {"name": r["name"], "kind": kind, "source_code": r["source"] or ""}
            for kind in ("Component", "Screen")
            for r in self._q(f"MATCH (n:{kind}) RETURN n.name AS name, n.source_code AS source")
        ]

    def _with_actions(self, components: list[dict]) -> list[dict]:
        """The components, each with its actions — read for all of them at once."""
        rows = self._q(
            "UNWIND $names AS cn MATCH (c:Component {name:cn})-[r:HAS_ACTION]->(a:Action) "
            "RETURN c.name AS name, a.trigger AS trigger, a.element AS element, a.handler AS handler, "
            "a.effect AS effect ORDER BY c.name, offset(ID(r))",
            {"names": [c["name"] for c in components]},
        )
        by_name: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            by_name[row.pop("name")].append(row)
        return [{**c, "actions": by_name.get(c["name"], [])} for c in components]
