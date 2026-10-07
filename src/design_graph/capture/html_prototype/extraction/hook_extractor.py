"""
The prototype's own hooks (`useDirtyGuard`, `useTweaks`): logic its
components and screens share, kept whole like a component — with what it
remembers and what its elements do — and linked to everyone who calls it.
"""

from __future__ import annotations

import re

from design_graph.capture.html_prototype.extraction.action_extractor import extract_actions
from design_graph.capture.html_prototype.extraction.state_extractor import extract_states
from design_graph.capture.html_prototype.sources import FunctionBoundary
from design_graph.model.entities import ComponentType, ExtractedComponent

_JSX = "jsx"
_RE_CALL = re.compile(r"(?<!function )(?<![\w$])(use[A-Z][\w$]*)\(")


def extract_hooks(js: str, boundaries: list[FunctionBoundary]) -> list[ExtractedComponent]:
    """One entry per hook declared in `js`, its source whole."""
    names = [boundary.name for boundary in boundaries]
    hooks: dict[str, ExtractedComponent] = {}
    for boundary in boundaries:
        source = js[boundary.start:boundary.end]
        hooks.setdefault(boundary.name, ExtractedComponent(
            name=boundary.name, comp_type=ComponentType.HOOK, source_code=source, source_lang=_JSX,
            occurrence=sum(match.group(1) == boundary.name for match in _RE_CALL.finditer(js)), classes="",
            actions=extract_actions(source, boundary.name), states=extract_states(source, boundary.name),
            hook_refs=hooks_called(source, names),
        ))
    return list(hooks.values())


def hooks_called(source: str, names: list[str]) -> list[str]:
    """The hooks among `names` that `source` calls, first call first — a `function useX(` declaring one is no call."""
    known = set(names)
    return list(dict.fromkeys(match.group(1) for match in _RE_CALL.finditer(source) if match.group(1) in known))
