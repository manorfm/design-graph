"""
Reading one screen for assembly: its own source as the skeleton, every
component it renders — each once, in the order it renders them — and the
tokens and resources it uses. Mixed into GraphReader, whose queries it uses.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict

from design_graph.model.entities import ComponentDefinitionStatus


class ScreenAssemblyQueries:
    """GraphReader's screen-assembly queries (relies on its _q, _resolve_icons and lookups)."""

    def get_screen_assembly(self, name: str) -> dict | None:
        """
        Everything needed to build one screen, each piece once: the screen's
        own source (its skeleton), every component it renders — directly or
        nested — in the order it renders them, and the tokens and resources
        the screen uses.
        """
        resolved = self._fuzzy_find_screen(name)
        if not resolved:
            return None
        screen = self._q(
            "MATCH (s:Screen {name:$n}) RETURN s.source_code AS source, s.skeleton AS skeleton, s.source_lang AS lang",
            {"n": resolved},
        )[0]
        return {
            "name": resolved,
            "skeleton": self._resolve_icons(screen["skeleton"] or screen["source"] or ""),
            "source_lang": screen["lang"] or "",
            "relations": self.get_screen_relations(resolved),
            "components": self._assembly_components(resolved, screen["skeleton"] or screen["source"] or ""),
            "tokens": self.get_tokens(screen=resolved),
            "resources": self.get_resources(screen=resolved),
        }

    def _assembly_components(self, screen: str, skeleton: str) -> list[dict]:
        """The screen's components, breadth first from the ones it uses directly, each once."""
        top = [r["name"] for r in self._q(
            "MATCH (s:Screen {name:$n})-[r:USES_COMPONENT]->(c:Component) RETURN c.name AS name ORDER BY offset(ID(r))",
            {"n": screen},
        )]
        children: dict[str, list[str]] = defaultdict(list)
        for r in self._q(
            "MATCH (s:Screen {name:$n})-[:USES_COMPONENT]->(:Component)-[:CONTAINS*0..3]->(p:Component) "
            "WITH DISTINCT p MATCH (p)-[r:CONTAINS]->(c:Component) "
            "RETURN p.name AS parent, c.name AS child ORDER BY p.name, r.order_index",
            {"n": screen},
        ):
            children[r["parent"]].append(r["child"])
        order: list[str] = []
        queue = list(dict.fromkeys(top))
        while queue:
            current = queue.pop(0)
            if current not in order:
                order.append(current)
                queue.extend(children.get(current, []))
        rows = {r["name"]: r for r in self._q(
            "UNWIND $names AS cn MATCH (c:Component {name:cn}) "
            "RETURN c.name AS name, c.comp_type AS comp_type, c.source_code AS source_code, "
            "c.source_lang AS source_lang, c.occurrence AS occurrence, c.referenced_data_json AS data",
            {"names": order},
        )}
        props: dict[str, list[dict]] = defaultdict(list)
        for r in self._q(
            "UNWIND $names AS cn MATCH (c:Component {name:cn})-[:HAS_PROP]->(p:ComponentProp) "
            "RETURN c.name AS name, p.prop_name AS prop_name, p.default_value AS default_value ORDER BY p.prop_name",
            {"names": order},
        ):
            props[r["name"]].append({"prop_name": r["prop_name"], "default_value": r["default_value"]})
        components = [
            {
                "name": name,
                "comp_type": rows[name]["comp_type"],
                "source_code": self._resolve_icons(rows[name]["source_code"] or ""),
                "source_lang": rows[name]["source_lang"] or "",
                "defined": rows[name]["occurrence"] != ComponentDefinitionStatus.UNRESOLVED.value,
                "props": props.get(name, []),
                "referenced_data": json.loads(rows[name]["data"] or "{}"),
            }
            for name in order if name in rows
        ]
        return _referenced(skeleton, components)


def _referenced(skeleton: str, components: list[dict]) -> list[dict]:
    """
    Only the components the skeleton — or a definition already sent — names:
    one whose markup is already written out inside another's definition is
    not sent a second time.
    """
    text, sent = skeleton, []
    for component in components:
        if re.search(rf"\b{re.escape(component['name'])}\b", text):
            sent.append(component)
            text += "\n" + component["source_code"]
    return sent
