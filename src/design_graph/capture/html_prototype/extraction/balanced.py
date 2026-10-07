"""Reading a JavaScript expression up to the bracket that closes it — strings respected."""

from __future__ import annotations

_QUOTES = "'\"`"
_PAIRS = {"{": "}", "(": ")", "[": "]"}


def closed_text(source: str, start: int, opener: str) -> str | None:
    """
    The text from `start` up to the `opener` bracket (already open just
    before `start`) closing, without it — None when it never closes.
    """
    closer, depth, index, quote = _PAIRS[opener], 1, start, ""
    while index < len(source):
        char = source[index]
        if quote:
            if char == "\\":
                index += 1
            elif char == quote:
                quote = ""
        elif char in _QUOTES:
            quote = char
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return source[start:index].strip()
        index += 1
    return None
