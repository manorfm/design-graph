"""
Actions of a React function: every `on*={…}` attribute in its source — the
event, the element or component it sits on, the handler whole (braces
balanced, strings respected) and what it does (capture.actions).
"""

from __future__ import annotations

import re

from design_graph.capture.actions import effect_of, trigger_of
from design_graph.model.entities import Action

_RE_EVENT_ATTRIBUTE = re.compile(r"\b(on[A-Z][\w$]*)=\{")
_RE_OPENING_TAG = re.compile(r"<([A-Za-z][\w.$]*)")
_QUOTES = "'\"`"


def extract_actions(source: str, owner: str) -> list[Action]:
    """Each event attribute in `source`, in order, once."""
    actions: dict[str, Action] = {}
    for match in _RE_EVENT_ATTRIBUTE.finditer(source):
        handler = _braced(source, match.end())
        if handler is None:
            continue
        tags = _RE_OPENING_TAG.findall(source, 0, match.start())
        action = Action.create(owner, trigger_of(match.group(1)), tags[-1] if tags else "", handler, effect_of(handler))
        actions.setdefault(action.id, action)
    return list(actions.values())


def _braced(source: str, start: int) -> str | None:
    """The text from `start` up to the brace closing the one just before it, or None when it never closes."""
    depth, index, quote = 1, start, ""
    while index < len(source):
        char = source[index]
        if quote:
            if char == "\\":
                index += 1
            elif char == quote:
                quote = ""
        elif char in _QUOTES:
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start:index].strip()
        index += 1
    return None
