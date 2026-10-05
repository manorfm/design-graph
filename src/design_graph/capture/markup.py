"""
The text a reader sees in a piece of markup, shared by every capture that
reads markup (DC templates, plain HTML sections).

A text node of rendered markup is copy by definition: whatever its length,
case or tag, it is kept. Only what the browser never shows (scripts, styles,
comments, doctypes) and template interpolations (`{{…}}`) are left out — unlike string
literals scanned out of code, which need TextEntry.reads_as_copy to tell copy
from code.
"""

from __future__ import annotations

from collections.abc import Callable, Collection

from bs4 import NavigableString, Tag
from bs4.element import PreformattedString

NOT_RENDERED: frozenset[str] = frozenset({"script", "style", "template", "noscript"})
INTERPOLATION = "{{"


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
