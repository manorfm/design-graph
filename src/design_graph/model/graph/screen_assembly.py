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


_RE_CODE_NAME = re.compile(r"[A-Za-z_$][\w$]*")
# A list named alike on several screens with other values is kept as `name · screen` (see the DC capture).
_SCREEN_SEPARATOR = " · "


def _belongs_to(key: str, screen: str, data: dict, named: set[str]) -> bool:
    """
    Whether one entry of a component's data is the screen's: its name is one
    the code uses, and — when it was kept apart per screen — it is this
    screen's copy, the plain one only when this screen has none of its own.
    """
    base, _, owner = key.partition(_SCREEN_SEPARATOR)
    if base not in named:
        return False
    if owner:
        return owner == screen
    return f"{base}{_SCREEN_SEPARATOR}{screen}" not in data


# A template loop over a list the page names — `list="{{rows}}"` — never an item's member (`{{u.items}}`) or a slot.
_RE_LOOP_LIST = re.compile(r"""\blist\s*=\s*["']\{\{\s*([A-Za-z_$][\w$]*)\s*\}\}["']""")


def _unread_lists(skeleton: str, components: list[dict], data: list[dict]) -> list[str]:
    """
    The lists the screen repeats — in its skeleton, its instances or its
    components' templates — that no data entry holds: built by the page's
    logic at run time, so only that logic tells what they contain.
    """
    held = {entry["key"].partition(_SCREEN_SEPARATOR)[0] for entry in data}
    repeated = _RE_LOOP_LIST.findall(skeleton)
    repeated += [name for c in components for name in _RE_LOOP_LIST.findall(c["source_code"])]
    return [name for name in dict.fromkeys(repeated) if name not in held]


class ScreenAssemblyQueries:
    """GraphReader's screen-assembly queries (relies on its _q, _resolve_icons and lookups)."""

    def get_screen_assembly(self, name: str) -> dict | None:
        """
        Everything needed to build one screen, each piece once: the screen's
        own source (its skeleton), every component it renders — directly or
        nested — in the order it renders them, then the prototype's own hooks
        they call, and the tokens and resources the screen uses.
        """
        resolved = self._fuzzy_find_screen(name)
        if not resolved:
            return None
        screen = self._q(
            "MATCH (s:Screen {name:$n}) RETURN s.source_code AS source, s.skeleton AS skeleton, s.source_lang AS lang",
            {"n": resolved},
        )[0]
        skeleton = screen["skeleton"] or screen["source"] or ""
        components = self._with_hooks(resolved, self._assembly_components(skeleton))
        data = self._screen_data(resolved, skeleton, components)
        return {
            "name": resolved,
            "skeleton": self._resolve_icons(skeleton),
            "source_lang": screen["lang"] or "",
            "relations": self.get_screen_relations(resolved),
            "components": components,
            "data": data,
            "unread_lists": _unread_lists(skeleton, components, data),
            "tokens": self.get_tokens(screen=resolved),
            "resources": self.get_resources(screen=resolved),
            "actions": self.actions_of("Screen", resolved),
            "states": self.states_of("Screen", resolved),
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

    def _screen_data(self, screen: str, skeleton: str, components: list[dict]) -> list[dict]:
        """
        The lists and tables the screen's components draw values from — the
        ones written out inside another definition too — each once, kept
        only when the screen's code or theirs names it: a repeated item
        carries every list it is repeated by, on every screen, and this
        screen needs its own.
        """
        named = set(_RE_CODE_NAME.findall(skeleton))
        named.update(word for c in components for word in _RE_CODE_NAME.findall(c["source_code"]))
        found: list[dict] = []
        for name, data in self._data_of_nested([c["name"] for c in components]):
            found += [
                {"component": name, "key": key, "value": value}
                for key, value in data.items() if _belongs_to(key, screen, data, named)
            ]
        return found

    def _data_of_nested(self, names: list[str]) -> list[tuple[str, dict]]:
        """(component, referenced data) of the components and everything they contain, each once, in that order."""
        order = list(dict.fromkeys(names))
        pending = order
        while pending:
            rows = self._q(
                "UNWIND $names AS pn MATCH (:Component {name:pn})-[:CONTAINS]->(c:Component) RETURN DISTINCT c.name AS name",
                {"names": pending},
            )
            pending = [r["name"] for r in rows if r["name"] not in order]
            order += pending
        rows = self._q(
            "UNWIND $names AS cn MATCH (c:Component {name:cn}) WHERE c.referenced_data_json <> '' "
            "RETURN c.name AS name, c.referenced_data_json AS data",
            {"names": order},
        )
        data = {r["name"]: json.loads(r["data"]) for r in rows}
        return [(name, data[name]) for name in order if isinstance(data.get(name), dict)]

    def _with_hooks(self, screen: str, components: list[dict]) -> list[dict]:
        """The components, then every hook the screen, they or those hooks call — each once, first call first."""
        known = {c["name"] for c in components}
        pending = self.hooks_of("Screen", screen)
        pending += [hook for c in components for hook in self.hooks_of("Component", c["name"])]
        hooks: list[dict] = []
        while pending:
            fresh = [name for name in dict.fromkeys(pending) if name not in known]
            known.update(fresh)
            found = self._components_named(fresh)
            hooks += [found[name] for name in fresh if name in found]
            pending = [h for name in fresh for h in self.hooks_of("Component", name)]
        return components + hooks

    def _components_named(self, names: list[str]) -> dict[str, dict]:
        """Each existing component among `names`, by exact name, with its props."""
        if not names:
            return {}
        rows = self._q(
            "UNWIND $names AS cn MATCH (c:Component {name:cn}) "
            "RETURN c.name AS name, c.comp_type AS comp_type, c.source_code AS source_code, "
            "c.source_lang AS source_lang, c.occurrence AS occurrence",
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
                "actions": self.actions_of("Component", row["name"]),
                "states": self.states_of("Component", row["name"]),
            }
            for row in rows
        }


_RE_TAG_USE = re.compile(r"<(\w[\w.-]*)|\{(\w+)\}")


def _tags_in(text: str) -> list[str]:
    """Names used as a tag (`<Name`) or passed as a value (`{Name}`), in order — candidates, not yet components."""
    return [tag or value for tag, value in _RE_TAG_USE.findall(text)]
