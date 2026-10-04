"""
The canvas layer of a DC prototype: boards laid out side by side, each an
iframe showing one page of the bundle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

_BOARD_PAGE_PREFIX = "about:blank#"
# "13 · Laudo" → board number 13, name "Laudo"
_RE_NUMBERED_TITLE = re.compile(r"^\s*(\d+)\s*[·.\-–—]\s*(.+)$")


@dataclass(frozen=True)
class Board:
    """One board of the canvas: the page it shows and the size it shows it at."""

    position: int    # 0-based order on the canvas
    title: str       # as authored, e.g. "1 · Boas-vindas (desktop)"
    number: int | None  # the author's own numbering, when the title has one
    name: str        # the title without its number — the screen's name
    page_id: str     # manifest id of the page
    width: int
    height: int


def read_boards(template: str) -> list[Board]:
    """Every board on the canvas, in canvas order; screens names made unique."""
    soup = BeautifulSoup(template, "html.parser")
    boards: list[Board] = []
    for section in soup.select("section.board"):
        frame = section.find("iframe")
        src = (frame.get("src") or "") if frame else ""
        if not src.startswith(_BOARD_PAGE_PREFIX):
            continue
        heading = section.find(["h1", "h2", "h3"])
        title = heading.get_text(" ", strip=True) if heading else (frame.get("title") or "")
        match = _RE_NUMBERED_TITLE.match(title)
        boards.append(Board(
            position=len(boards),
            title=title,
            number=int(match.group(1)) if match else None,
            name=match.group(2).strip() if match else title,
            page_id=src[len(_BOARD_PAGE_PREFIX):],
            width=_pixels(frame.get("width")),
            height=_pixels(frame.get("height")),
        ))
    return _with_unique_names(boards)


def _pixels(value: str | None) -> int:
    digits = re.match(r"\s*(\d+)", value or "")
    return int(digits.group(1)) if digits else 0


def _with_unique_names(boards: list[Board]) -> list[Board]:
    """Two boards sharing a name keep their full titles instead, so no screen is lost."""
    seen: dict[str, int] = {}
    for board in boards:
        seen[board.name] = seen.get(board.name, 0) + 1
    unique: list[Board] = []
    for board in boards:
        if seen[board.name] > 1:
            board = Board(**{**board.__dict__, "name": board.title})
        unique.append(board)
    return unique
