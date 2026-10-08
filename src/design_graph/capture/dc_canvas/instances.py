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

from design_graph.capture.dc_canvas.template import drop_authoring_hints, is_authoring_hint

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

@dataclass(frozen=True)
class _Position:
    """One value that may vary between occurrences: a text, an attribute, or one declaration of a style."""

    node: object
    attribute: str | None   # None for a text
    declaration: int | None  # which `;`-separated declaration of a style attribute
    value: str
    name: str                # what its slot is called


def _shape(node) -> tuple:
    """
    What must match for two occurrences to share a template: elements,
    attribute names and the properties each style declares, in order, all
    the way down.
    """
    if isinstance(node, Tag):
        style = _with_slots(node.get("style") or "", {}, blank=True)
        attributes = tuple(sorted(a for a in node.attrs if not is_authoring_hint(node, a)))
        return (node.name, attributes, style, tuple(_shape(child) for child in node.children))
    if isinstance(node, PreformattedString):  # comments and the like: kept verbatim, part of the shape
        return ("#literal", str(node))
    return ("#text",)


def _positions(node) -> list[_Position]:
    """Every value that may vary, in document order."""
    found: list[_Position] = []
    if isinstance(node, Tag):
        for name in node.attrs:
            if is_authoring_hint(node, name):
                continue
            if name == "style":
                found += [_Position(node, name, index, value, prop)
                          for index, (prop, value) in enumerate(_declarations(node.attrs[name]))]
            else:
                found.append(_Position(node, name, None, _attribute(node, name), name))
        for child in node.children:
            found.extend(_positions(child))
    elif not isinstance(node, PreformattedString):
        found.append(_Position(node, None, None, str(node), "texto"))
    return found


def _declarations(style: str) -> list[tuple[str, str]]:
    """(property, value) of each declaration of a style attribute, in order."""
    found = []
    for segment in style.split(";"):
        prop, colon, value = segment.partition(":")
        if colon:
            found.append((prop.strip().lower(), value.strip()))
    return found


def _with_slots(style: str, slots: dict[int, str], blank: bool = False) -> str:
    """
    A style attribute with the values of some declarations swapped for slot
    markers — spacing and separators kept as written. `blank` swaps every
    value, leaving the frame a style is written in: what two occurrences must
    share to fill one template exactly.
    """
    segments, index = style.split(";"), 0
    for n, segment in enumerate(segments):
        prop, colon, value = segment.partition(":")
        if not colon:
            continue
        if blank or index in slots:
            lead = value[: len(value) - len(value.lstrip())]
            trail = value[len(value.rstrip()):]
            segments[n] = f"{prop}{colon}{lead}{'' if blank else slot_marker(slots[index])}{trail}"
        index += 1
    return ";".join(segments)


def _attribute(tag: Tag, name: str) -> str:
    value = tag.attrs[name]
    return " ".join(value) if isinstance(value, list) else value


# ── Definitions ───────────────────────────────────────────────────────────────

def representative(occurrences: list[Tag]) -> Tag:
    """The occurrence a component is described by: the first of those sharing the most common shape."""
    return _most_common_shape(occurrences)[0]


def _most_common_shape(occurrences: list[Tag]) -> list[Tag]:
    """The occurrences sharing the most common shape, in order; ties go to the shape seen first."""
    shapes = [_shape(element) for element in occurrences]
    common = Counter(shapes).most_common(1)[0][0]
    return [element for element, shape in zip(occurrences, shapes) if shape == common]


def definition_of(occurrences: list[Tag]) -> Definition:
    """The template of the occurrences sharing the most common shape; the others are left out of it."""
    same = _most_common_shape(occurrences)
    template = copy.copy(same[0])
    drop_authoring_hints(template)
    columns = list(zip(*(_positions(element) for element in same)))
    slots: list[tuple[str, str]] = []
    values: dict[int, dict[str, str]] = {id(element): {} for element in same}
    style_slots: dict[int, tuple[Tag, dict[int, str]]] = {}
    used: set[str] = set()
    for column, position in zip(columns, _positions(template)):
        observed = [p.value for p in column]
        if len(set(observed)) == 1:
            continue
        slot = _unique(position.name, used)
        slots.append((slot, observed[0]))
        for element, value in zip(same, observed):
            values[id(element)][slot] = value
        if position.attribute is None:
            position.node.replace_with(slot_marker(slot))
        elif position.declaration is None:
            position.node.attrs[position.attribute] = slot_marker(slot)
        else:
            style_slots.setdefault(id(position.node), (position.node, {}))[1][position.declaration] = slot
    for node, by_declaration in style_slots.values():
        node.attrs["style"] = _with_slots(node.attrs["style"], by_declaration)
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
        return _RE_TEXT_SLOT.sub(lambda m: html.escape(values.get(m.group(1), m.group(0)), quote=True), filled)

    return _RE_INSTANCE.sub(expand, skeleton)
