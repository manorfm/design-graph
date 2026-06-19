"""
Identify React screen/page functions and collect their direct component references.

A function is a Screen if its name ends in one of the semantic suffixes
defined by RE_SCREEN_NAME (Page, Screen, Dashboard, etc.).

Screen extraction is a read-only scan of the JS string — no side effects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from design_graph.core.constants import REACT_INTERNALS
from design_graph.core.models import ExtractedScreen, FunctionBoundary
from design_graph.core.patterns import (
    RE_COMP_REF,
    RE_JSX_CALL,
    RE_JSX_TAG,
)
from design_graph.extraction.visual_function import VisualFunctionCandidate

logger = logging.getLogger(__name__)


class ScreenRole(str, Enum):
    PAGE = "page"
    VIEW = "view"
    DETAIL = "detail"
    COMPONENT = "component"


@dataclass(frozen=True)
class ScreenIdentity:
    """Semantic identity that distinguishes navigation surfaces from UI parts."""

    name: str
    role: ScreenRole

    @classmethod
    def classify(cls, name: str) -> "ScreenIdentity":
        if name.endswith("Form") and name.startswith(("Login", "SignIn", "SignUp", "Register", "Auth")):
            return cls(name=name, role=ScreenRole.PAGE)
        suffix_roles = (
            (("Page", "Screen", "Dashboard"), ScreenRole.PAGE),
            (("View",), ScreenRole.VIEW),
            (("Detail",), ScreenRole.DETAIL),
        )
        for suffixes, role in suffix_roles:
            if name.endswith(suffixes) and len(name) > min(len(suffix) for suffix in suffixes):
                return cls(name=name, role=role)
        return cls(name=name, role=ScreenRole.COMPONENT)

    @property
    def is_top_level(self) -> bool:
        return self.role is not ScreenRole.COMPONENT


def is_screen(name: str) -> bool:
    """Return True only for semantic top-level navigation surfaces."""
    return ScreenIdentity.classify(name).is_top_level


def extract_screens(
    js: str,
    all_boundaries: list[FunctionBoundary],
) -> list[ExtractedScreen]:
    """
    Filter boundaries to those representing screens, then collect the
    PascalCase component names each screen references in its body.

    Returns screens in their source order.
    """
    screens: list[ExtractedScreen] = []

    for boundary in all_boundaries:
        candidate = VisualFunctionCandidate.from_source(js, boundary)
        if not is_screen(boundary.name) or not candidate.renders_visual_output:
            continue

        body = js[boundary.start : boundary.end]
        component_refs = _collect_component_refs(body, exclude=boundary.name)

        screens.append(ExtractedScreen(
            name=boundary.name,
            component_refs=sorted(component_refs),
            sections_count=0,
        ))

        logger.debug(
            "screen_extractor: %s → %d direct refs",
            boundary.name, len(component_refs),
        )

    return screens


# ── Private helpers ───────────────────────────────────────────────────────────

def _collect_component_refs(body: str, exclude: str) -> set[str]:
    """
    Scan a function body and collect all PascalCase component references,
    excluding React internals and the function's own name.
    """
    refs: set[str] = set()

    for pattern in (RE_JSX_TAG, RE_JSX_CALL, RE_COMP_REF):
        for match in pattern.finditer(body):
            name = match.group(1)
            if name not in REACT_INTERNALS and name != exclude and len(name) >= 3:
                refs.add(name)

    return refs
