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
            "components": self._assembly_components(screen["skeleton"] or screen["source"] or ""),
            "tokens": self.get_tokens(screen=resolved),
            "resources": self.get_resources(screen=resolved),
            "actions": self.actions_of("Screen", resolved),
        }

    def _assembly_components(self, skeleton: str) -> list[dict]:
        """
        The components the skeleton uses as tags — then the ones their own
        definitions use — each once, in the order they are first used. A
        component whose markup is already written out inside another
        definition is never sent again, and a word in a text is never a use.
        """
        order: list[str] = []
        components: dict[str, dict] = {}
        pending = _tags_in(skeleton)
        while pending:
            found = self._components_named([name for name in dict.fromkeys(pending) if name not in components])
            components.update(found)
            fresh = [name for name in dict.fromkeys(pending) if name in components and name not in order]
            order += fresh
            pending = [tag for name in fresh for tag in _tags_in(components[name]["source_code"])]
        return [components[name] for name in order]

    def _components_named(self, names: list[str]) -> dict[str, dict]:
        """Each existing component among `names`, by exact name, with its props."""
        if not names:
            return {}
        rows = self._q(
            "UNWIND $names AS cn MATCH (c:Component {name:cn}) "
            "RETURN c.name AS name, c.comp_type AS comp_type, c.source_code AS source_code, "
            "c.source_lang AS source_lang, c.occurrence AS occurrence, c.referenced_data_json AS data",
            {"names": names},
        )
        props: dict[str, list[dict]] = defaultdict(list)
        for r in self._q(
            "UNWIND $names AS cn MATCH (c:Component {name:cn})-[:HAS_PROP]->(p:ComponentProp) "
            "RETURN c.name AS name, p.prop_name AS prop_name, p.default_value AS default_value ORDER BY p.prop_name",
            {"names": names},
        ):
            props[r["name"]].append({"prop_name": r["prop_name"], "default_value": r["default_value"]})
        return {
            row["name"]: {
                "name": row["name"],
                "comp_type": row["comp_type"],
                "source_code": self._resolve_icons(row["source_code"] or ""),
                "source_lang": row["source_lang"] or "",
                "defined": row["occurrence"] != ComponentDefinitionStatus.UNRESOLVED.value,
                "props": props.get(row["name"], []),
                "referenced_data": json.loads(row["data"] or "{}"),
                "actions": self.actions_of("Component", row["name"]),
            }
            for row in rows
        }


_RE_TAG_USE = re.compile(r"<(\w[\w.-]*)|\{(\w+)\}")


def _tags_in(text: str) -> list[str]:
    """Names used as a tag (`<Name`) or passed as a value (`{Name}`), in order — candidates, not yet components."""
    return [tag or value for tag, value in _RE_TAG_USE.findall(text)]
