"""
Listings of everything a prototype's graph holds — sections, props, sources,
actions — for search, each component's or screen's actions, and what one
screen holds, to compare variants. Mixed into GraphReader, whose queries it uses.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class CatalogQueries:
    """GraphReader's catalog and action queries (relies on its _q and _fuzzy_find_screen)."""

    def screen_contents(self, name: str) -> dict | None:
        """
        What a screen holds, each sorted and once: the components it renders
        (nested ones included), its sections' texts and its style declarations
        (`prop: value`, from its own elements and its sections') — the sets
        two variants of a screen are told apart by.
        """
        resolved = self._fuzzy_find_screen(name)
        if not resolved:
            return None
        components = self._q(
            "MATCH (:Screen {name:$n})-[:USES_COMPONENT]->(:Component)-[:CONTAINS*0..3]->(c:Component) "
            "RETURN DISTINCT c.name AS value",
            {"n": resolved},
        )
        texts = self._q(
            "MATCH (:Screen {name:$n})-[:HAS_SECTION]->(:Section)-[:SECTION_HAS_TEXT]->(t:UIText) "
            "RETURN DISTINCT t.content AS value",
            {"n": resolved},
        )
        styles = self._q(
            "MATCH (s:Screen {name:$n})-[:SCREEN_HAS_STYLE]->(st:Style) "
            "RETURN st.property + ': ' + st.value AS value "
            "UNION MATCH (:Screen {name:$n})-[:HAS_SECTION]->(:Section)-[:SECTION_HAS_STYLE]->(st:Style) "
            "RETURN st.property + ': ' + st.value AS value",
            {"n": resolved},
        )
        return {"name": resolved, **{
            key: sorted({row["value"] for row in rows})
            for key, rows in (("components", components), ("texts", texts), ("styles", styles))
        }}

    def actions_of(self, kind: str, name: str) -> list[dict]:
        """A component's or screen's actions, in the order its source declares them."""
        relation = "HAS_ACTION" if kind == "Component" else "SCREEN_HAS_ACTION"
        return self._q(
            f"MATCH (n:{kind} {{name:$n}})-[r:{relation}]->(a:Action) "
            "RETURN a.trigger AS trigger, a.element AS element, a.handler AS handler, a.effect AS effect "
            "ORDER BY offset(ID(r))",
            {"n": name},
        )

    def hooks_of(self, kind: str, name: str) -> list[str]:
        """The prototype's own hooks a component or screen calls, in the order it calls them."""
        relation = "USES_HOOK" if kind == "Component" else "SCREEN_USES_HOOK"
        rows = self._q(
            f"MATCH (n:{kind} {{name:$n}})-[r:{relation}]->(h:Component) RETURN h.name AS name ORDER BY offset(ID(r))",
            {"n": name},
        )
        return [row["name"] for row in rows]

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

    def list_referenced_data(self) -> list[dict]:
        """Every component's referenced data — the lists and tables it draws values from — for searching their copy."""
        found = []
        for row in self._q(
            "MATCH (c:Component) WHERE c.referenced_data_json <> '' "
            "RETURN c.name AS name, c.referenced_data_json AS data"
        ):
            try:
                data = json.loads(row["data"])
            except json.JSONDecodeError:
                logger.warning("listing: unreadable referenced data of %s", row["name"])
                continue
            if isinstance(data, dict):
                found.append({"name": row["name"], "data": data})
        return found

    def states_of(self, kind: str, name: str) -> list[dict]:
        """A component's or screen's states, in the order its source declares them."""
        relation = "HAS_STATE" if kind == "Component" else "SCREEN_HAS_STATE"
        return self._q(
            f"MATCH (n:{kind} {{name:$n}})-[r:{relation}]->(s:State) "
            "RETURN s.name AS name, s.initial AS initial ORDER BY offset(ID(r))",
            {"n": name},
        )

    def list_states(self) -> list[dict]:
        """Every state, with the component or screen it belongs to."""
        return self._q("MATCH (s:State) RETURN s.owner AS owner, s.name AS name, s.initial AS initial")

    def _with_actions(self, components: list[dict]) -> list[dict]:
        """The components, each with its actions and states — read for all of them at once."""
        rows = self._q(
            "UNWIND $names AS cn MATCH (c:Component {name:cn})-[r:HAS_ACTION]->(a:Action) "
            "RETURN c.name AS name, a.trigger AS trigger, a.element AS element, a.handler AS handler, "
            "a.effect AS effect ORDER BY c.name, offset(ID(r))",
            {"names": [c["name"] for c in components]},
        )
        by_name: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            by_name[row.pop("name")].append(row)
        states: dict[str, list[dict]] = defaultdict(list)
        for row in self._q(
            "UNWIND $names AS cn MATCH (c:Component {name:cn})-[r:HAS_STATE]->(s:State) "
            "RETURN c.name AS owner, s.name AS name, s.initial AS initial ORDER BY c.name, offset(ID(r))",
            {"names": [c["name"] for c in components]},
        ):
            states[row.pop("owner")].append(row)
        return [{**c, "actions": by_name.get(c["name"], []), "states": states.get(c["name"], [])} for c in components]
