"""
What an element looks like, and what a container holds, in words a name can
carry — `Caps`, `Serif`, `Pill`, `Accent`, `Decorative`, `Bold`, `Small`,
`Large`; `Heading`, `Button`, `Chart` — read only from its own literal
styles, attributes and child elements, never guessed from its copy. A
component living in differently named places is told apart by these
instead of by a number alone (`CapsBoldTag`, `SerifLargeHeading`, `HeadingStack`).
"""

from __future__ import annotations

import re
from typing import Callable

from bs4 import Tag

from design_graph.capture.dc_canvas.template import element_children, inline_styles, tag_of
from design_graph.capture.markup import INTERPOLATION

_ROUND = {"50%", "100%", "999px", "9999px"}
_SMALL_PX = 13
_LARGE_PX = 24
# The first size a value states: `12px`, or the floor of `clamp(30px, 4.2vw, 52px)`.
_RE_FIRST_PX = re.compile(r"^(?:clamp\(\s*)?([\d.]+)px")


def traits_of(element: Tag) -> list[str]:
    """The traits the element shows, most telling first."""
    styles = {prop: value for prop, value in inline_styles(element).items() if INTERPOLATION not in value}
    return [trait for trait, shows in _TRAITS if shows(styles, element)]


def shared_traits(elements: list[Tag]) -> list[str]:
    """The traits every element shows, in the order the first one shows them."""
    if not elements:
        return []
    found = traits_of(elements[0])
    for element in elements[1:]:
        found = [trait for trait in found if trait in traits_of(element)]
    return found


def main_content(element: Tag) -> str:
    """The most telling kind of element among its children (`Heading`, `Button`…), or "" when none tells anything."""
    kinds = {_CONTENT_BY_TAG.get(tag_of(child)) for child in element_children(element)}
    return next((kind for kind in _CONTENT_RANK if kind in kinds), "")


def _caps(styles: dict[str, str], _: Tag) -> bool:
    return styles.get("text-transform") == "uppercase"


def _serif(styles: dict[str, str], _: Tag) -> bool:
    family = styles.get("font-family", "").lower()
    return "serif" in family.replace("sans-serif", "")


def _pill(styles: dict[str, str], _: Tag) -> bool:
    return styles.get("border-radius") in _ROUND and "inline" in styles.get("display", "")


def _accent(styles: dict[str, str], _: Tag) -> bool:
    background = styles.get("background", "") or styles.get("background-color", "")
    return "var(--accent)" in background


def _decorative(_: dict[str, str], element: Tag) -> bool:
    return element.get("aria-hidden") == "true"


def _bold(styles: dict[str, str], _: Tag) -> bool:
    weight = styles.get("font-weight", "")
    return weight == "bold" or (weight.isdigit() and int(weight) >= 600)


def _small(styles: dict[str, str], _: Tag) -> bool:
    size = _first_px(styles.get("font-size", ""))
    return size is not None and size <= _SMALL_PX


def _large(styles: dict[str, str], _: Tag) -> bool:
    size = _first_px(styles.get("font-size", ""))
    return size is not None and size >= _LARGE_PX


def _first_px(value: str) -> float | None:
    found = _RE_FIRST_PX.match(value.strip())
    return float(found.group(1)) if found else None


_TRAITS: list[tuple[str, Callable[[dict[str, str], Tag], bool]]] = [
    ("Caps", _caps), ("Serif", _serif), ("Pill", _pill), ("Accent", _accent), ("Decorative", _decorative),
    ("Bold", _bold), ("Small", _small), ("Large", _large),
]

# What a container holds, most telling first: a form or a heading says more about it than a link does.
_CONTENT_RANK = ["Fieldset", "Form", "Table", "Heading", "Chart", "List", "Image", "Field", "Button", "Link", "Legend", "Label"]
_CONTENT_BY_TAG = {
    "fieldset": "Fieldset", "form": "Form", "table": "Table", **{f"h{n}": "Heading" for n in range(1, 7)},
    "svg": "Chart", "ul": "List", "ol": "List", "img": "Image", "input": "Field", "select": "Field", "textarea": "Field",
    "button": "Button", "a": "Link", "legend": "Legend", "label": "Label",
}
