"""
Reading a DC template as the page it renders, without rewriting it: loop and
condition directives (<sc-for>, <sc-if>) are transparent containers, raw
elements (<sc-raw-table>…) are the element they stand for, and interpolated
values ({{…}}) are never mistaken for copy or style literals.
"""

from __future__ import annotations

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from design_graph.model.entities import TextEntry

_TRANSPARENT = {"sc-for", "sc-if"}
_RAW_PREFIX = "sc-raw-"
_NOT_RENDERED = {"script", "style", "helmet", "template"}
INTERPOLATION = "{{"
# Every stored DC source — page, block or component — is template markup.
SOURCE_LANG = "html-template"


def parse_markup(markup: str) -> BeautifulSoup:
    return BeautifulSoup(markup, "html.parser")


def tag_of(element: Tag) -> str:
    """The element a node renders as — `sc-raw-td` renders a `td`."""
    name = element.name or ""
    return name[len(_RAW_PREFIX):] if name.startswith(_RAW_PREFIX) else name


def element_children(element: Tag) -> list[Tag]:
    """Rendered child elements, looking through loop/condition directives."""
    children: list[Tag] = []
    for child in element.children:
        if not isinstance(child, Tag) or child.name in _NOT_RENDERED:
            continue
        children.extend(element_children(child) if child.name in _TRANSPARENT else [child])
    return children


def visible_texts(element: Tag) -> list[str]:
    """The literal copy an element shows, in reading order, each once."""
    texts: dict[str, None] = {}
    for node in element.descendants:
        if not isinstance(node, NavigableString) or isinstance(node, Comment):
            continue
        if any(parent.name in _NOT_RENDERED for parent in node.parents if isinstance(parent, Tag)):
            continue
        text = " ".join(node.split())
        if text and INTERPOLATION not in text and TextEntry.is_plausible_content(text):
            texts[text] = None
    return list(texts)


def inline_styles(element: Tag) -> dict[str, str]:
    """An element's own literal style declarations; interpolated values are left out."""
    styles: dict[str, str] = {}
    for declaration in (element.get("style") or "").split(";"):
        prop, sep, value = declaration.partition(":")
        prop, value = prop.strip().lower(), value.strip()
        if sep and prop and value and INTERPOLATION not in value:
            styles[prop] = value
    return styles
