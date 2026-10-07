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
        elif char in "]})" or (char == "," and depth == 0):
            if depth == 0:
                break
            depth -= 1
        index += 1
    return text[start:index].strip()
