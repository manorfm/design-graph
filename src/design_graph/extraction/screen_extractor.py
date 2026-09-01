"""
Identify React screen/page functions and collect their direct component references.

A function is a Screen if ScreenIdentity.classify() assigns it a non-COMPONENT
role — a deliberately narrower set of suffixes than a blunt regex would give:
Panel/Tab/List/Section/Modal are excluded because they're usually reusable
UI parts (ConfirmModal, SettingsPanel), not top-level navigation surfaces.

Screen extraction is a read-only scan of the JS string — no side effects.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from design_graph.core.constants import REACT_INTERNALS
from design_graph.core.models import ExtractedScreen, FunctionBoundary, StrEnum
from design_graph.core.patterns import (
    RE_COMP_REF,
    RE_JSX_CALL,
    RE_JSX_TAG,
)
from design_graph.extraction.icon_extractor import extract_icons
from design_graph.extraction.jsx_sanitizer import sanitize_jsx
from design_graph.extraction.visual_function import VisualFunctionCandidate
from design_graph.parsing.js_parser import extract_return_block

logger = logging.getLogger(__name__)

# A full-page overlay/editor shell (e.g. ItemEditorV6) conditionally
# switches between 2+ of its own Tab-suffixed children — the shape of a
# multi-tab editor root, regardless of what its own name ends in.
_MIN_TAB_SWITCHES_FOR_OVERLAY = 2
_RE_TAB_TAG_HINT = re.compile(r'<(?:[A-Za-z_$][\w$]*\.)?(\w*Tab)\b')
_RE_CONDITIONAL_TAB_MARKER = re.compile(r'\{\[(?:conditional|either):[^}]*Tab[^}]*\]\}')


class ScreenRole(StrEnum):
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


def _is_overlay_shell(body: str) -> bool:
    """
    Structural counterpart to ScreenIdentity's name-based classification:
    a function whose own body conditionally switches between 2+ of its
    own Tab-suffixed children is a multi-tab editor shell, whatever its
    name ends in. `_RE_TAB_TAG_HINT` is a cheap pre-filter — sanitize_jsx
    only runs when there's already a real chance of a match, since this
    is checked against every candidate boundary in the file.
    """
    if not body or len(_RE_TAB_TAG_HINT.findall(body)) < _MIN_TAB_SWITCHES_FOR_OVERLAY:
        return False
    sanitized = sanitize_jsx(body)
    return len(_RE_CONDITIONAL_TAB_MARKER.findall(sanitized)) >= _MIN_TAB_SWITCHES_FOR_OVERLAY


def is_screen(name: str, body: str = "") -> bool:
    """
    True for a semantic top-level navigation surface (name-based), or for
    a full-page overlay shell recognised by structure (see
    _is_overlay_shell) — never by reopening ScreenIdentity's deliberate
    suffix exclusions (C17: Panel/Tab/List/Section/Modal usually name
    reusable UI parts, not navigation surfaces).
    """
    return ScreenIdentity.classify(name).is_top_level or _is_overlay_shell(body)


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
        body = js[boundary.start : boundary.end]
        if not is_screen(boundary.name, body) or not candidate.renders_visual_output:
            continue

        component_refs = _collect_component_refs(body, exclude=boundary.name)
        jsx_snippet, icons = _extract_screen_jsx(js, boundary)

        screens.append(ExtractedScreen(
            name=boundary.name,
            component_refs=component_refs,
            sections_count=0,
            jsx_snippet=jsx_snippet,
            icons=icons,
        ))

        logger.debug(
            "screen_extractor: %s → %d direct refs",
            boundary.name, len(component_refs),
        )

    return screens


# ── Private helpers ───────────────────────────────────────────────────────────

def _extract_screen_jsx(js: str, boundary: FunctionBoundary) -> tuple[str, list]:
    """
    The screen's own return-block, sanitized the same way an
    ExtractedComponent's jsx_snippet is: icons pulled out first (so the
    sanitizer and every downstream reader only ever see the short marker),
    then sanitize_jsx collapses dynamic expressions.
    """
    jsx_raw = extract_return_block(js, boundary.start, boundary.end, body_start=boundary.body_start)
    if not jsx_raw:
        return "", []
    jsx_with_icon_refs, icons = extract_icons(jsx_raw)
    return sanitize_jsx(jsx_with_icon_refs), icons


def _collect_component_refs(body: str, exclude: str) -> list[str]:
    """
    Scan a function body and collect all PascalCase component references,
    excluding React internals and the function's own name, in
    first-appearance order (not alphabetical — same first-appearance
    approximation extraction/component_extractor.py uses for a component's
    own child_refs, so a screen's top-level component order is recoverable
    without re-reading raw JSX, the same as C30 already gives a component's
    own children).
    """
    seen: set[str] = set()
    refs: list[str] = []

    for pattern in (RE_JSX_TAG, RE_JSX_CALL, RE_COMP_REF):
        for match in pattern.finditer(body):
            name = match.group(1)
            if name not in REACT_INTERNALS and name != exclude and len(name) >= 3 and name not in seen:
                seen.add(name)
                refs.append(name)

    return refs
