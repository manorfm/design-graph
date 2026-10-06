"""
Definitions with slots, and screens as skeletons of instances.

Occurrences of a DC component that share one shape — the same elements and
attribute names all the way down — are one definition: whatever is the same
in every occurrence stays literal; a text or attribute value that differs
becomes a slot, written `{{slot.name}}`. In each screen's skeleton every
outermost occurrence becomes an instance tag carrying its slot values
(`<Footer href="A02-….dc.html" texto="Página 2"></Footer>`). Occurrences of
another shape stay literal.

Expanding a skeleton with the definitions gives the page back (same tree,
attributes and texts): expand_skeleton is that invariant, kept next to what
it checks.
"""

from __future__ import annotations

import copy
import html
import re
from collections import Counter
from dataclasses import dataclass, field

from bs4 import Tag
from bs4.element import PreformattedString

_RE_INSTANCE = re.compile(r'<([A-Z][\w-]*)((?:\s+[\w:.-]+="[^"]*")*)\s*></\1>')
_RE_ATTRIBUTE = re.compile(r'([\w:.-]+)="([^"]*)"')
_RE_ATTRIBUTE_SLOT = re.compile(r'="\{\{slot\.([\w-]+)\}\}"')
_RE_TEXT_SLOT = re.compile(r"\{\{slot\.([\w-]+)\}\}")


def slot_marker(name: str) -> str:
    return f"{{{{slot.{name}}}}}"


@dataclass
class Definition:
    """A component's template and, for each of its occurrences of that shape, its slot values."""

    markup: str
    slots: list[tuple[str, str]]                      # (slot, first occurrence's value), in document order
    values: dict[int, dict[str, str]] = field(default_factory=dict)  # id(occurrence) → slot → value


# ── Shapes and positions ──────────────────────────────────────────────────────

def _shape(node) -> tuple:
    """What must match for two occurrences to share a template: elements and attribute names, all the way down."""
    if isinstance(node, Tag):
        return (node.name, tuple(sorted(node.attrs)), tuple(_shape(child) for child in node.children))
    if isinstance(node, PreformattedString):  # comments and the like: kept verbatim, part of the shape
        return ("#literal", str(node))
    return ("#text",)


def _positions(node) -> list[tuple]:
    """Every value that may vary, in document order: (node, attribute name or None for a text, value)."""
    found: list[tuple] = []
    if isinstance(node, Tag):
        for name in node.attrs:
            found.append((node, name, _attribute(node, name)))
        for child in node.children:
            found.extend(_positions(child))
    elif not isinstance(node, PreformattedString):
        found.append((node, None, str(node)))
    return found


def _attribute(tag: Tag, name: str) -> str:
    value = tag.attrs[name]
    return " ".join(value) if isinstance(value, list) else value


# ── Definitions ───────────────────────────────────────────────────────────────

def definition_of(occurrences: list[Tag]) -> Definition:
    """The template of the occurrences sharing the most common shape; the others are left out of it."""
    shapes = [_shape(element) for element in occurrences]
    common = Counter(shapes).most_common(1)[0][0]
    same = [element for element, shape in zip(occurrences, shapes) if shape == common]
    template = copy.copy(same[0])
    columns = list(zip(*(_positions(element) for element in same)))
    slots: list[tuple[str, str]] = []
    values: dict[int, dict[str, str]] = {id(element): {} for element in same}
    used: set[str] = set()
    for column, (node, attribute, _) in zip(columns, _positions(template)):
        observed = [value for _, _, value in column]
        if len(set(observed)) == 1:
            continue
        slot = _unique(attribute or "texto", used)
        slots.append((slot, observed[0]))
        for element, value in zip(same, observed):
            values[id(element)][slot] = value
        if attribute is None:
            node.replace_with(slot_marker(slot))
        else:
            node.attrs[attribute] = slot_marker(slot)
    return Definition(markup=str(template), slots=slots, values=values)


def _unique(name: str, used: set[str]) -> str:
    candidate, n = name, 2
    while candidate in used:
        candidate, n = f"{name}{n}", n + 1
    used.add(candidate)
    return candidate


# ── Skeletons ─────────────────────────────────────────────────────────────────

def replace_with_instances(root: Tag, name_of: dict[int, str], definitions: dict[str, Definition]) -> None:
    """Swap every outermost occurrence that fits its definition for an instance tag carrying its slot values."""
    for child in list(root.children):
        if not isinstance(child, Tag):
            continue
        name = name_of.get(id(child))
        definition = definitions.get(name) if name else None
        if definition is not None and id(child) in definition.values:
            instance = Tag(name=name, attrs=dict(definition.values[id(child)]))
            child.replace_with(instance)
        else:
            replace_with_instances(child, name_of, definitions)


def expand_skeleton(skeleton: str, templates: dict[str, str]) -> str:
    """
    The markup a skeleton stands for: each instance tag replaced by its
    definition, slots filled. Instances are matched as written — a PascalCase
    tag, case and all — so `<Footer …>` never swallows a real `<footer>`.
    """
    def expand(match: re.Match) -> str:
        name, raw_attributes = match.group(1), match.group(2)
        if name not in templates:
            return match.group(0)
        values = {key: html.unescape(value) for key, value in _RE_ATTRIBUTE.findall(raw_attributes)}
        filled = _RE_ATTRIBUTE_SLOT.sub(
            lambda m: f'="{html.escape(values.get(m.group(1), m.group(0)), quote=True)}"', templates[name],
        )
        return _RE_TEXT_SLOT.sub(lambda m: html.escape(values.get(m.group(1), m.group(0)), quote=False), filled)

    return _RE_INSTANCE.sub(expand, skeleton)
