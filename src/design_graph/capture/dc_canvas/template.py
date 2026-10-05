"""
Reading a DC template as the page it renders, without rewriting it: loop and
condition directives (<sc-for>, <sc-if>) are transparent containers, raw
elements (<sc-raw-table>…) are the element they stand for, and interpolated
values ({{…}}) are never mistaken for copy or style literals.
"""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from design_graph.capture import markup
from design_graph.capture.markup import INTERPOLATION

_TRANSPARENT = {"sc-for", "sc-if"}
_RAW_PREFIX = "sc-raw-"
_NOT_RENDERED = markup.NOT_RENDERED | {"helmet"}
# Every stored DC source — page, block or component — is template markup.
SOURCE_LANG = "html-template"


def parse_markup(source: str) -> BeautifulSoup:
    return BeautifulSoup(source, "html.parser")


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
    """The copy an element shows, in reading order, each once."""
    return markup.visible_texts(element, not_rendered=_NOT_RENDERED)


def visible_text_nodes(element: Tag) -> list[tuple[str, str]]:
    """Each copy an element shows, once, with the tag of the element showing it."""
    return markup.visible_text_nodes(element, tag_of=tag_of, not_rendered=_NOT_RENDERED)


def rendered_descendants(element: Tag) -> list[Tag]:
    """Every rendered element below `element`, in document order."""
    found: list[Tag] = []
    for child in element_children(element):
        found.append(child)
        found.extend(rendered_descendants(child))
    return found


def inline_styles(element: Tag) -> dict[str, str]:
    """An element's own literal style declarations; interpolated values are left out."""
    styles: dict[str, str] = {}
    for declaration in (element.get("style") or "").split(";"):
        prop, sep, value = declaration.partition(":")
        prop, value = prop.strip().lower(), value.strip()
        if sep and prop and value and INTERPOLATION not in value:
            styles[prop] = value
    return styles
