"""
Values a DC page's logic writes literally — `[{ id: 'cap', label: 'Por
capacidade' }]` — read from its text, never run: strings, numbers, booleans,
null, lists and objects, in JSON or JavaScript syntax.

A name is read only when the caller binds it (a factory's parameter), and a
call only to a function the caller defines (a factory itself). An
object member whose value is behaviour — a call, a condition, a handler — is
left out of the object, since it is not data; anything else that is not a
literal refuses the whole value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Mapping

Calls = Mapping[str, Callable[[list], object]]  # function name → what a call with these arguments gives

# Deeper than any data a page declares; stops a crafted page from exhausting the stack.
MAX_DEPTH = 64

_RE_NUMBER = re.compile(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_RE_NAME = re.compile(r"[A-Za-z_$][\w$]*")
_RE_SPACE = re.compile(r"(?:\s+|//[^\n]*|/\*.*?\*/)*", re.S)
_KEYWORDS = {"true": True, "false": False, "null": None, "undefined": None}
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}
_QUOTES = "\"'`"


class NotALiteral(ValueError):
    """The text at that point is not a value written literally."""


@dataclass(frozen=True)
class Literal:
    value: object
    end: int  # index just past the value


def read_literal(
    text: str, start: int, names: Mapping[str, object] | None = None, calls: Calls | None = None,
) -> Literal:
    """
    The value written at `start`; `names` binds the names it may use and
    `calls` the functions it may call. Raises NotALiteral.
    """
    reader = _Reader(text, names or {}, calls or {})
    reader.index = start
    value = reader.value(0)
    return Literal(value, reader.index)


def string_end(text: str, start: int) -> int:
    """Index of the quote closing the string opened at `start` (or the text's end)."""
    index = start + 1
    while index < len(text) and text[index] != text[start]:
        index += 2 if text[index] == "\\" else 1
    return index


def expression_at(text: str, start: int) -> str:
    """The expression from `start` up to the comma, semicolon or bracket that ends it, strings and nesting respected."""
    depth, index = 0, start
    while index < len(text):
        char = text[index]
        if char in _QUOTES:
            index = string_end(text, index)
        elif char in "[{(":
            depth += 1
        elif char in "]})" or (char in ",;" and depth == 0):
            if depth == 0:
                break
            depth -= 1
        index += 1
    return text[start:index]


class _Reader:
    def __init__(self, text: str, names: Mapping[str, object], calls: Calls):
        self.text, self.names, self.calls, self.index = text, names, calls, 0

    def value(self, depth: int) -> object:
        if depth > MAX_DEPTH:
            raise NotALiteral("nested too deep")
        char = self._peek()
        if not char:
            raise NotALiteral("text ends before a value")
        if char == "[":
            return self._list(depth)
        if char == "{":
            return self._object(depth)
        if char in _QUOTES:
            return self._string()
        number = _RE_NUMBER.match(self.text, self.index)
        if number:
            self.index = number.end()
            return float(number.group()) if any(c in number.group() for c in ".eE") else int(number.group())
        return self._name(depth)

    def _list(self, depth: int, closing: str = "]") -> list:
        self.index += 1
        items: list = []
        while self._peek() != closing:
            items.append(self.value(depth + 1))
            if not self._separator(closing):
                raise NotALiteral(f"list item ends unexpectedly at {self.index}")
        self.index += 1
        return items

    def _object(self, depth: int) -> dict:
        self.index += 1
        members: dict = {}
        while self._peek() != "}":
            start = self.index
            try:
                key, value = self._member(depth)
                members[key] = value
            except NotALiteral:
                self.index = start + len(expression_at(self.text, start))
            if not self._separator("}"):
                raise NotALiteral(f"object member ends unexpectedly at {self.index}")
        self.index += 1
        return members

    def _member(self, depth: int) -> tuple[str, object]:
        char = self._peek()
        if char and char in _QUOTES:
            key = self._string()
        else:
            found = _RE_NAME.match(self.text, self.index) or _RE_NUMBER.match(self.text, self.index)
            if not found:
                raise NotALiteral(f"no member name at {self.index}")
            key, self.index = found.group(), found.end()
            if self._peek() in ",}" and key in self.names:
                return key, self.names[key]
        if self._peek() != ":":
            raise NotALiteral(f"member {key!r} has no literal value")
        self.index += 1
        value = self.value(depth + 1)
        if self._peek() not in ",}":
            raise NotALiteral(f"member {key!r} continues past its value")
        return key, value

    def _separator(self, closing: str) -> bool:
        """Past the comma after an item; True when the list or object goes on or closes here."""
        char = self._peek()
        if char == ",":
            self.index += 1
            return True
        return char == closing

    def _string(self) -> str:
        quote, start = self.text[self.index], self.index
        end = string_end(self.text, start)
        if end >= len(self.text):
            raise NotALiteral("unterminated string")
        raw = self.text[start + 1:end]
        if quote == "`" and "${" in raw:
            raise NotALiteral("interpolated template")
        self.index = end + 1
        return _unescape(raw)

    def _name(self, depth: int) -> object:
        found = _RE_NAME.match(self.text, self.index)
        if not found:
            raise NotALiteral(f"no value at {self.index}")
        name = found.group()
        self.index = found.end()
        if self._peek() == "(":
            if name not in self.calls:
                raise NotALiteral(f"call to {name!r}")
            return self.calls[name](self._list(depth, closing=")"))
        if name in _KEYWORDS:
            value = _KEYWORDS[name]
        elif name in self.names:
            value = self.names[name]
        else:
            raise NotALiteral(f"unbound name {name!r}")
        return value

    def _peek(self) -> str:
        self.index = _RE_SPACE.match(self.text, self.index).end()
        return self.text[self.index] if self.index < len(self.text) else ""


def _unescape(raw: str) -> str:
    out, index = [], 0
    while index < len(raw):
        char = raw[index]
        if char != "\\" or index + 1 == len(raw):
            out.append(char)
            index += 1
            continue
        code, index = raw[index + 1], index + 2
        if code in "ux":
            digits = 4 if code == "u" else 2
            hex_digits = raw[index:index + digits]
            if len(hex_digits) == digits and all(c in "0123456789abcdefABCDEF" for c in hex_digits):
                out.append(chr(int(hex_digits, 16)))
                index += digits
                continue
        if code != "\n":  # a backslash before a newline continues the line
            out.append(_ESCAPES.get(code, code))
    return "".join(out)
