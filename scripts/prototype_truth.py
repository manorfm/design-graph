"""
What a prototype really says, read straight from its own pages — never
through the capture being checked — so the graph can be measured against
it: each DC page's markup, the texts a reader of it sees, its inline style
declarations, and whether some markup renders exactly as a page does.

Shared by the context benchmark (scripts/context_benchmark.py) and the
checks run against real prototypes (tests/prototypes/).
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from design_graph.capture.base import PrototypeDocument
from design_graph.capture.bundler import read_bundle
from design_graph.capture.dc_canvas.canvas import read_boards
from design_graph.capture.dc_canvas.page import DcPage, read_page

_NOT_RENDERED = {"script", "style", "helmet", "template"}
_INTERPOLATION = "{{"
_RE_STYLE_ATTRIBUTE = re.compile(r'style="([^"]*)"')
# Attributes the canvas editor reads to preview a loop or a condition; the page renders without them.
# Spelled out here instead of borrowed from the capture: the yardstick must not share the capture's rules.
_DIRECTIVES = {"sc-for", "sc-if"}
_EDITOR_HINT = "hint-"


def dc_pages(document: PrototypeDocument) -> dict[str, DcPage]:
    """Screen name → the DC page its board shows, for every board whose page can be read."""
    bundle = read_bundle(document.text)
    pages = {}
    for board in read_boards(bundle.template) if bundle else []:
        page = read_page(bundle.entry(board.page_id).decode("utf-8", errors="replace"))
        if page is not None:
            pages[board.name] = page
    return pages


def visible_texts(markup: str) -> set[str]:
    """Every literal text node a reader of the page sees, whitespace-collapsed."""
    texts = set()
    for node in BeautifulSoup(markup, "html.parser").find_all(string=True):
        if isinstance(node, Comment) or any(p.name in _NOT_RENDERED for p in node.parents if p.name):
            continue
        text = " ".join(node.split())
        if text and _INTERPOLATION not in text:
            texts.add(text)
    return texts


def style_declarations(markup: str) -> set[str]:
    """Every literal inline style declaration, normalized as `property: value`."""
    return {
        declaration
        for attribute in _RE_STYLE_ATTRIBUTE.findall(markup)
        for declaration in map(normalized_declaration, attribute.split(";"))
        if declaration
    }


def normalized_declaration(raw: str) -> str | None:
    prop, sep, value = raw.partition(":")
    prop, value = prop.strip().lower(), " ".join(value.split())
    if not sep or not prop or not value or _INTERPOLATION in value:
        return None
    return f"{prop}: {value}"


def rendering_difference(rebuilt: str, written: str) -> str | None:
    """
    None when `rebuilt` renders exactly as `written` does — same elements,
    attributes, style declarations and texts, in the same order — else
    where the first difference is. Spacing, comments, the order of a
    style's declarations and the editor's hints do not render, so they do
    not count; styles and logic around the markup are checked on their own.
    """
    return _first_difference(_rendered(BeautifulSoup(rebuilt, "html.parser")),
                             _rendered(BeautifulSoup(written, "html.parser")), "page")


def _rendered(node: Tag) -> list[tuple]:
    found: list[tuple] = []
    for child in node.children:
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            text = " ".join(str(child).split())
            if text:
                found.append(("#text", text))
        elif isinstance(child, Tag) and child.name not in _NOT_RENDERED:
            found.append((child.name, _attributes(child), _rendered(child)))
    return found


def _attributes(element: Tag) -> tuple:
    kept = []
    for name, value in element.attrs.items():
        if element.name in _DIRECTIVES and name.startswith(_EDITOR_HINT):
            continue
        value = " ".join(value) if isinstance(value, list) else value
        kept.append((name, tuple(sorted(filter(None, map(normalized_declaration, value.split(";")))))
                     if name == "style" else value))
    return tuple(sorted(kept))


def _first_difference(rebuilt: list[tuple], written: list[tuple], path: str) -> str | None:
    for index, (mine, theirs) in enumerate(zip(rebuilt, written)):
        if mine == theirs:
            continue
        if mine[0] == theirs[0] != "#text" and mine[1] == theirs[1]:
            return _first_difference(mine[2], theirs[2], f"{path} > {mine[0]}[{index}]")
        return f"{path}[{index}]: rebuilt {_short(mine)} where the page has {_short(theirs)}"
    if len(rebuilt) != len(written):
        return f"{path}: rebuilt {len(rebuilt)} nodes where the page has {len(written)}"
    return None


def _short(node: tuple) -> str:
    return repr(node[:2])[:240]
