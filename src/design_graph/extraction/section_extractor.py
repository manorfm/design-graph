"""
Detect named visual sections within a React screen function.

Detection strategy (cascade — first that yields quality sections wins):
  1. JSX comment markers: {/* ── Name ── */}
  2. Structural fallback: <div> blocks with substantial padding/margin
  3. Empty list if neither produces quality sections

Quality threshold: a section must have >= 1 component ref, OR >= 2 texts,
OR >= 3 style properties. This prevents empty sections from polluting the graph.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re

from design_graph.core.constants import MAX_SECTIONS_FROM_STRUCTURAL_FALLBACK
from design_graph.core.models import ExtractedSection, ExtractedScreen, FunctionBoundary
from design_graph.core.patterns import (
    RE_CLASS_NAME,
    RE_COMP_REF,
    RE_INLINE_STYLE,
    RE_JSX_TAG,
    RE_PLACEHOLDER,
    RE_SECTION_COMMENT,
    RE_STYLE_PROP,
    RE_UI_STRING,
)

logger = logging.getLogger(__name__)

# Minimum padding/margin value (px) that signals a visual separator
_STRUCTURAL_PADDING_THRESHOLD = 16


def extract_sections(
    js: str,
    screen: ExtractedScreen,
    boundary: FunctionBoundary,
) -> list[ExtractedSection]:
    """
    Extract named sections from a screen's return block.
    Tries comment detection first, falls back to structural detection.
    Returns an empty list if nothing qualifies.
    """
    if boundary.end <= boundary.start:
        return []

    window = js[boundary.start : boundary.end]

    sections = _detect_by_comments(window, screen.name)
    if sections:
        logger.debug(
            "section_extractor: %s → %d sections via comments",
            screen.name, len(sections),
        )
        return _apply_quality_filter(sections)

    sections = _detect_by_structure(window, screen.name)
    if sections:
        logger.debug(
            "section_extractor: %s → %d sections via structural fallback",
            screen.name, len(sections),
        )
        return _apply_quality_filter(sections)

    logger.debug("section_extractor: %s → no sections detected", screen.name)
    return []


# ── Strategy 1: JSX comment markers ──────────────────────────────────────────

def _detect_by_comments(window: str, screen_name: str) -> list[ExtractedSection]:
    comment_positions = [
        (m.start(), m.end(), m.group(1).strip())
        for m in RE_SECTION_COMMENT.finditer(window)
    ]

    if not comment_positions:
        return []

    sections: list[ExtractedSection] = []
    for i, (c_start, c_end, sec_name) in enumerate(comment_positions):
        next_start = comment_positions[i + 1][0] if i + 1 < len(comment_positions) else c_end + 4_000
        block = window[c_end:next_start]

        sections.append(_build_section(
            block=block,
            sec_name=sec_name,
            screen_name=screen_name,
            detection_method="comment",
        ))

    return sections


# ── Strategy 2: Structural fallback (padding-heavy divs) ──────────────────────

_PADDING_RE = re.compile(
    r'style=\{\{[^}]*(?:padding|margin)\s*:\s*["\']?(\d+)px'
)


def _detect_by_structure(window: str, screen_name: str) -> list[ExtractedSection]:
    """
    Find <div> blocks with padding >= threshold as section separators.
    Returns at most MAX_SECTIONS_FROM_STRUCTURAL_FALLBACK sections.
    """
    candidate_positions: list[tuple[int, int]] = []

    for m in _PADDING_RE.finditer(window):
        try:
            px = int(m.group(1))
        except ValueError:
            continue
        if px >= _STRUCTURAL_PADDING_THRESHOLD:
            # Capture the enclosing block: from the nearest '<div' before this match
            div_start = window.rfind("<div", 0, m.start())
            if div_start >= 0:
                # Find rough end of this div (next closing </div> or 4000 chars)
                div_end = window.find("</div>", m.start())
                if div_end < 0:
                    div_end = m.start() + 4_000
                else:
                    div_end += 6  # include </div>
                candidate_positions.append((div_start, div_end))

    # De-duplicate heavily overlapping candidates
    unique: list[tuple[int, int]] = []
    for start, end in candidate_positions:
        if not unique or start > unique[-1][1] - 200:
            unique.append((start, end))

    unique = unique[:MAX_SECTIONS_FROM_STRUCTURAL_FALLBACK]

    sections: list[ExtractedSection] = []
    for i, (start, end) in enumerate(unique):
        block = window[start:end]
        # Use first UI text as section name
        texts_in_block = [m.group(1).strip() for m in RE_UI_STRING.finditer(block)]
        sec_name = next(
            (t for t in texts_in_block if len(t) > 3 and not t.startswith("#")),
            f"Section{i + 1}",
        )
        sections.append(_build_section(
            block=block,
            sec_name=sec_name,
            screen_name=screen_name,
            detection_method="structural",
        ))

    return sections


# ── Section builder ───────────────────────────────────────────────────────────

def _build_section(
    block: str,
    sec_name: str,
    screen_name: str,
    detection_method: str,
) -> ExtractedSection:
    sec_id = _hid(f"{screen_name}_{sec_name}", "sec_")

    # Styles
    styles: dict[str, str] = {}
    for sm in RE_INLINE_STYLE.finditer(block):
        for prop, val in RE_STYLE_PROP.findall(sm.group(1)):
            val = val.strip().rstrip(",").strip()
            if val and val not in ("true", "false", "null", "undefined"):
                styles[prop] = val

    # Component references
    comp_refs: set[str] = set()
    for pattern in (RE_JSX_TAG, RE_COMP_REF):
        for m in pattern.finditer(block):
            name = m.group(1)
            if len(name) >= 3:
                comp_refs.add(name)

    # Texts
    texts: list[str] = []
    seen_texts: set[str] = set()
    for m in RE_UI_STRING.finditer(block):
        t = m.group(1).strip()
        if t not in seen_texts and 3 < len(t) < 80 and not t.startswith("#"):
            seen_texts.add(t)
            texts.append(t)
    for m in RE_PLACEHOLDER.finditer(block):
        t = m.group(1).strip()
        if t not in seen_texts:
            seen_texts.add(t)
            texts.append(f"[placeholder] {t}")
    texts = texts[:15]

    return ExtractedSection(
        id=sec_id,
        screen=screen_name,
        name=sec_name,
        styles=styles,
        component_refs=sorted(comp_refs),
        texts=texts,
        jsx_snippet=block[:3_000].strip(),
        detection_method=detection_method,
    )


# ── Quality filter ────────────────────────────────────────────────────────────

def _qualifies(section: ExtractedSection) -> bool:
    return (
        len(section.component_refs) >= 1
        or len(section.texts) >= 2
        or len(section.styles) >= 3
    )


def _apply_quality_filter(sections: list[ExtractedSection]) -> list[ExtractedSection]:
    return [s for s in sections if _qualifies(s)]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hid(s: str, prefix: str = "") -> str:
    return f"{prefix}{hashlib.md5(s.encode()).hexdigest()[:8]}"
