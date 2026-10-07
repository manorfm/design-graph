"""State of a React function: every `const [x, setX] = useState(initial)` in it, the initial value as written."""

from __future__ import annotations

import re

from design_graph.capture.html_prototype.extraction.balanced import closed_text
from design_graph.model.entities import State

_RE_USE_STATE = re.compile(r"\bconst\s*\[\s*([\w$]+)\s*,\s*[\w$]+\s*\]\s*=\s*(?:React\.)?useState\(")


def extract_states(source: str, owner: str) -> list[State]:
    """Each state `source` declares, in order, once."""
    states: dict[str, State] = {}
    for match in _RE_USE_STATE.finditer(source):
        initial = closed_text(source, match.end(), "(")
        if initial is not None:
            states.setdefault(match.group(1), State.create(owner, match.group(1), initial))
    return list(states.values())
