"""
The copy a component's referenced data holds — the labels of a list of
options, the titles of a table — for search. A value counts as copy when it
reads as words; drawing data such as an SVG path, a color or a measure does
not, and is left out so it never crowds the answer.
"""

from __future__ import annotations

import re

# A whole word of letters: "faixa" in "faixa 18–31%", never the "px" of "12px" or the "L" of an SVG path.
_RE_WORD = re.compile(r"(?<!\w)[^\W\d_]{2,}(?!\w)")
_RE_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}")
# Longer strings are prose or encoded data, not something an agent searches for by phrase.
MAX_COPY_LENGTH = 300


def copy_in(data: dict[str, object]) -> list[tuple[str, str]]:
    """(list or table name, copy) for each string in `data` that reads as copy, once each, in order."""
    found: dict[tuple[str, str], None] = {}
    for name, value in data.items():
        pending = [value]
        while pending:
            item = pending.pop()
            if isinstance(item, str):
                if reads_as_copy(item):
                    found.setdefault((name, item))
            elif isinstance(item, dict):
                pending.extend(reversed(list(item.values())))
            elif isinstance(item, list):
                pending.extend(reversed(item))
    return list(found)


def reads_as_copy(text: str) -> bool:
    """Holds a whole word of two letters or more, is not a color, and is short enough to be searched by phrase."""
    stripped = text.strip()
    return (
        len(stripped) <= MAX_COPY_LENGTH
        and not _RE_COLOR.fullmatch(stripped)
        and bool(_RE_WORD.search(stripped))
    )
