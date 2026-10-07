"""
Literal data a DC page's logic class declares — `const papel = [{…}, …]` —
read without running the logic: only a list that is plain JSON is taken.
"""

from __future__ import annotations

import json
import re

_RE_LIST_DECLARATION = re.compile(r"\b(?:const|let|var)\s+(\w+)\s*=\s*\[")


def literal_lists(logic: str) -> dict[str, list]:
    """Name → value of every list the logic declares as a JSON literal."""
    found: dict[str, list] = {}
    for declaration in _RE_LIST_DECLARATION.finditer(logic):
        start = declaration.end() - 1
        end = _closing_bracket(logic, start)
        if end is None:
            continue
        try:
            value = json.loads(logic[start:end + 1])
        except json.JSONDecodeError:
            continue
        found.setdefault(declaration.group(1), value)
    return found


def _closing_bracket(text: str, start: int) -> int | None:
    """Index of the `]` closing the `[` at `start`, skipping brackets inside strings."""
    depth, index = 0, start
    while index < len(text):
        char = text[index]
        if char in "\"'`":
            index = _string_end(text, index)
        elif char in "[{(":
            depth += 1
        elif char in "]})":
            depth -= 1
            if depth == 0:
                return index if char == "]" else None
        index += 1
    return None


def _string_end(text: str, start: int) -> int:
    """Index of the quote closing the string opened at `start` (or the text's end)."""
    index = start + 1
    while index < len(text) and text[index] != text[start]:
        index += 2 if text[index] == "\\" else 1
    return index


def member_expression(logic: str, key: str) -> str | None:
    """
    The expression the logic gives a member named `key` — `pick: () =>
    this.setState({ papel: o.id })` → `() => this.setState({ papel: o.id })` —
    read up to the comma or brace that ends it, strings and nesting respected.
    """
    for match in re.finditer(rf"\b{re.escape(key)}\s*:\s*", logic):
        expression = _expression_at(logic, match.end())
        if expression:
            return expression
    return None


def _expression_at(text: str, start: int) -> str:
    depth, index = 0, start
    while index < len(text):
        char = text[index]
        if char in "\"'`":
            index = _string_end(text, index)
        elif char in "[{(":
            depth += 1
        elif char in "]})" or (char in ",;" and depth == 0):
            if depth == 0:
                break
            depth -= 1
        index += 1
    return text[start:index].strip()


_RE_STATE_VARIABLE = re.compile(r"\b(?:const|let|var)\s+([\w$]+)\s*=\s*this\.state\b")
_RE_SELECTION = re.compile(
    r"^(?P<condition>.+?)\s*\?\s*(?P<chosen>'[^']*'|\"[^\"]*\")\s*:\s*(?P<other>'[^']*'|\"[^\"]*\")$", re.S
)
_RE_PICKS_ITEM = re.compile(r"===\s*[\w$]+\.id\b|\b[\w$]+\.id\s*===")


def state_defaults(logic: str) -> list[tuple[str, str]]:
    """
    (name, default) of each state the logic reads with a fallback —
    `s.papel ?? "eng"`, where `s` holds `this.state` — in order, once.
    """
    holders = {"this.state", *(f"{name}" for name in _RE_STATE_VARIABLE.findall(logic))}
    found: dict[str, str] = {}
    for holder in holders:
        pattern = re.compile(rf"(?<![\w$.]){re.escape(holder)}\.([\w$]+)\s*\?\?\s*")
        for match in pattern.finditer(logic):
            found.setdefault(match.group(1), _expression_at(logic, match.end()))
    return sorted(found.items(), key=lambda item: logic.find(f".{item[0]}"))


def selection_branches(expression: str) -> tuple[str, str] | None:
    """(value when the item is the selected one, value otherwise) of `x === o.id ? 'a' : 'b'`, or None."""
    match = _RE_SELECTION.match(expression.strip())
    if not match or not _RE_PICKS_ITEM.search(match.group("condition")):
        return None
    return match.group("chosen")[1:-1], match.group("other")[1:-1]
