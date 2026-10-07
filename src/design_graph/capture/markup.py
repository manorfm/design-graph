"""
The text a reader sees in a piece of markup, shared by every capture that
reads markup (DC templates, plain HTML sections).

A text node of rendered markup is copy by definition: whatever its length,
case or tag, it is kept. Only what the browser never shows (scripts, styles,
comments, doctypes) and template interpolations (`{{…}}`) are left out — unlike string
literals scanned out of code, which need TextEntry.reads_as_copy to tell copy
from code.

Hints are the copy a reader meets without it being shown in the flow: a
field's placeholder, a title or aria-label, and the description of a chart —
an svg that is not hidden from readers and draws data marks.
"""

from __future__ import annotations

from collections.abc import Callable, Collection

from bs4 import NavigableString, Tag
from bs4.element import PreformattedString

NOT_RENDERED: frozenset[str] = frozenset({"script", "style", "template", "noscript"})
INTERPOLATION = "{{"
_HINT_ATTRIBUTES = (("placeholder", "placeholder"), ("title", "dica"), ("aria-label", "dica"))
_DATA_MARKS = ("circle", "rect", "polygon", "polyline", "line", "path")
_MIN_CHART_MARKS = 3
_MIN_HINT_CHARS = 3


def _element_name(element: Tag) -> str:
    return element.name or ""


def visible_text_nodes(
    root: Tag,
    tag_of: Callable[[Tag], str] = _element_name,
    not_rendered: Collection[str] = NOT_RENDERED,
) -> list[tuple[str, str]]:
    """Each text `root` shows, once, in reading order, with the tag of the element showing it."""
    found: dict[str, str] = {}
    for node in root.descendants:
        if not isinstance(node, NavigableString) or isinstance(node, PreformattedString):
            continue
        if any(parent.name in not_rendered for parent in node.parents if isinstance(parent, Tag)):
            continue
        text = " ".join(node.split())
        if text and INTERPOLATION not in text:
            found.setdefault(text, tag_of(node.parent))
    return list(found.items())


def visible_texts(root: Tag, not_rendered: Collection[str] = NOT_RENDERED) -> list[str]:
    """Each text `root` shows, once, in reading order."""
    return [text for text, _ in visible_text_nodes(root, not_rendered=not_rendered)]


def hint_texts(root: Tag, not_rendered: Collection[str] = NOT_RENDERED) -> list[str]:
    """Each hint below `root`, once, in document order: `[placeholder] …`, `[dica] …`, `[gráfico] …`."""
    found: dict[str, None] = {}
    for element in [root, *root.find_all(True)]:
        if element.name in not_rendered or any(parent.name in not_rendered for parent in element.parents):
            continue
        chart = _is_chart(element)
        for attribute, kind in _HINT_ATTRIBUTES:
            value = " ".join(str(element.get(attribute) or "").split())
            if len(value) >= _MIN_HINT_CHARS and INTERPOLATION not in value:
                found.setdefault(f"[{'gráfico' if chart else kind}] {value}")
    return list(found)


def _is_chart(element: Tag) -> bool:
    if element.name != "svg" or element.get("aria-hidden") == "true":
        return False
    return len(element.find_all(_DATA_MARKS)) >= _MIN_CHART_MARKS
