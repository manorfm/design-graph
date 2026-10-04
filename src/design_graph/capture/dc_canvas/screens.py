"""
How the boards of a canvas relate: which board a page link leads to, and
which boards are variants of another (the same page at another viewport or
in another mode).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from design_graph.capture.dc_canvas.canvas import Board
from design_graph.capture.dc_canvas.page import DcPage
from design_graph.model.entities import ScreenLink

_PAGE_SUFFIX = ".dc.html"
# The page DC authors open first; its board leads the canvas.
_ENTRY_PAGE = "Main"
# "A02-Perspectiva" → 2: the author's board number heads the page's file name.
_RE_FILE_NUMBER = re.compile(r"^[A-Za-z]*0*(\d+)\b")
# "Boas-vindas (desktop)" → base "Boas-vindas"
_RE_VARIANT_TITLE = re.compile(r"^(.*\S)\s*\(([^()]+)\)\s*$")


@dataclass(frozen=True)
class Variant:
    base: str
    axis: str


def variants(boards: list[Board], pages: dict[str, DcPage]) -> dict[str, Variant]:
    """Board name → the base board it varies, for every board titled "Base (what varies)"."""
    by_name = {board.name: board for board in boards}
    found: dict[str, Variant] = {}
    for board in boards:
        match = _RE_VARIANT_TITLE.match(board.name)
        base = by_name.get(match.group(1)) if match else None
        if base is None or base is board:
            continue
        found[board.name] = Variant(base=base.name, axis=_variation_axis(board, base, pages))
    return found


def _variation_axis(board: Board, base: Board, pages: dict[str, DcPage]) -> str:
    if (board.width, board.height) != (base.width, base.height):
        return "viewport"
    page, base_page = pages[board.page_id], pages[base.page_id]
    if any(page.default(prop) != base_page.default(prop) for prop in page.props):
        return "mode"
    return "variant"


def links(page: DcPage, boards: list[Board], variant_names: set[str]) -> list[ScreenLink]:
    """Every link of the page that leads to a board of this canvas, in page order."""
    bases = [board for board in boards if board.name not in variant_names]
    found = []
    for anchor in BeautifulSoup(page.markup, "html.parser").find_all("a", href=True):
        target = _board_for_file(anchor["href"], bases)
        if target is not None:
            label = anchor.get_text(" ", strip=True) or anchor.get("aria-label", "") or anchor.get("title", "")
            found.append(ScreenLink(target=target.name, label=label))
    return found


def _board_for_file(href: str, bases: list[Board]) -> Board | None:
    if not href.endswith(_PAGE_SUFFIX) or "/" in href:
        return None
    stem = href[: -len(_PAGE_SUFFIX)]
    if stem == _ENTRY_PAGE:
        return bases[0] if bases else None
    number = _RE_FILE_NUMBER.match(stem)
    if not number:
        return None
    return next((board for board in bases if board.number == int(number.group(1))), None)
