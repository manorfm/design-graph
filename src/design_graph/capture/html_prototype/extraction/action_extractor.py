"""
Actions of a React function: every `on*={…}` attribute in its source — the
event, the element or component it sits on, the handler whole (braces
balanced, strings respected — see balanced.py) and what it does (capture.actions).
"""

from __future__ import annotations

import re

from design_graph.capture.actions import effect_of, trigger_of
from design_graph.capture.html_prototype.extraction.balanced import closed_text
from design_graph.model.entities import Action

_RE_EVENT_ATTRIBUTE = re.compile(r"\b(on[A-Z][\w$]*)=\{")
_RE_OPENING_TAG = re.compile(r"<([A-Za-z][\w.$]*)")


def extract_actions(source: str, owner: str) -> list[Action]:
    """Each event attribute in `source`, in order, once."""
    actions: dict[str, Action] = {}
    for match in _RE_EVENT_ATTRIBUTE.finditer(source):
        handler = closed_text(source, match.end(), "{")
        if handler is None:
            continue
        tags = _RE_OPENING_TAG.findall(source, 0, match.start())
        action = Action.create(owner, trigger_of(match.group(1)), tags[-1] if tags else "", handler, effect_of(handler))
        actions.setdefault(action.id, action)
    return list(actions.values())
