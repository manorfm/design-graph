"""
Detect named visual sections within a screen.

Detection strategy cascade — first that yields quality sections wins:
  1. JSX comment markers: {/* ── Name ── */}       (React / bundled_react)
  2. Structural fallback: <div> blocks with substantial padding/margin
  3. Semantic fallback: HTML5 elements (nav/header/main/section/footer) (plain_html)

Strategy 3 is triggered via extract_sections_for_plain_html() which accepts
a BeautifulSoup object instead of a raw JS string.

Quality threshold: a section must have >= 1 component ref, OR >= 2 texts,
OR >= 3 style properties. This prevents empty sections from polluting the graph.
"""

from __future__ import annotations

import json
import logging
import re

from bs4 import BeautifulSoup

from design_graph.core.constants import (
    JS_FUNCTION_FALLBACK_WINDOW,
    JS_FUNCTION_SCAN_LIMIT,
    MAX_SECTIONS_FROM_STRUCTURAL_FALLBACK,
)
from design_graph.core.models import (
    DetectionMethod,
    ExtractedScreen,
    ExtractedSection,
    FunctionBoundary,
)
from design_graph.parsing.html_parser import extract_semantic_sections
from design_graph.parsing.js_parser import iter_style_object_blocks, parse_object_literal_props
from design_graph.core.patterns import (
    RE_COMP_REF,
    RE_JSX_TAG,
    RE_PLACEHOLDER,
    RE_SECTION_COMMENT,
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

_MAX_SECTION_LABEL_CHARS = 40


def _section_label(raw_comment_text: str) -> str:
    """
    Derive a short, displayable section name from a comment's raw captured
    text (RE_SECTION_COMMENT's generous, boundary-detection-only capture).

    A descriptive comment routinely elaborates past its own name
    (`Painel unico: tabs + descricao + conteudo compartilham a mesma
    superficie`) — the same `label: elaboration` convention its author
    already used to separate the two, so the phrase before the first `:`
    is the label. A comment with no `:` (`── Header ──`) is short by
    construction and used whole, hard-capped only as a last resort against
    a pathological one-sentence comment with no punctuation at all.
    """
    label = raw_comment_text.split(":", 1)[0].strip()
    if len(label) > _MAX_SECTION_LABEL_CHARS:
        label = label[:_MAX_SECTION_LABEL_CHARS].rstrip()
    return label


def _detect_by_comments(window: str, screen_name: str) -> list[ExtractedSection]:
    comment_positions = [
        (m.start(), m.end(), _section_label(m.group(1)))
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
            detection_method=DetectionMethod.COMMENT,
        ))

    return sections


# ── Strategy 2: Structural fallback (padding-heavy divs) ──────────────────────

_PADDING_RE = re.compile(
    r'style=\{\{[^}]*(?:padding|margin)\s*:\s*["\']?(\d+)px'
)
_DIV_OPEN_RE = re.compile(r"<div\b")
_DIV_CLOSE = "</div>"


def _find_balanced_div_end(window: str, div_start: int) -> int:
    """
    Return the index just past the </div> that closes the <div at div_start,
    counting nested <div>/</div> pairs instead of stopping at the first
    </div> found anywhere after the match — a padded container almost
    always has nested children, so an unbalanced find() cuts the section off
    at the first child's closing tag instead of the container's own.

    Not JS-string-aware (unlike find_matching_delimiter, which skips string/
    template literals for JS brace matching) — "<div"/"</div>" appearing
    inside a text string is rare enough in real prototypes that a plain
    balanced scan is a proportionate fix for this structural fallback
    heuristic. Falls back to a fixed window when no balanced close is found
    within the scan limit (malformed/truncated snippet).
    """
    depth = 0
    limit = min(len(window), div_start + JS_FUNCTION_SCAN_LIMIT)
    pos = div_start
    while pos < limit:
        open_match = _DIV_OPEN_RE.search(window, pos, limit)
        close_pos = window.find(_DIV_CLOSE, pos, limit)
        if close_pos == -1:
            break
        if open_match and open_match.start() < close_pos:
            depth += 1
            pos = open_match.end()
        else:
            depth -= 1
            pos = close_pos + len(_DIV_CLOSE)
            if depth <= 0:
                return pos
    return min(div_start + JS_FUNCTION_FALLBACK_WINDOW, len(window))


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
                div_end = _find_balanced_div_end(window, div_start)
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
            detection_method=DetectionMethod.STRUCTURAL,
        ))

    return sections


# ── Section builder ───────────────────────────────────────────────────────────

def _build_section(
    block: str,
    sec_name: str,
    screen_name: str,
    detection_method: DetectionMethod,
) -> ExtractedSection:
    # Styles
    styles: dict[str, str] = {}
    for style_block in iter_style_object_blocks(block):
        for prop, val in parse_object_literal_props(style_block):
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

    return ExtractedSection.create(
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


# ── Strategy 3: Semantic detection (plain HTML) ───────────────────────────────

def extract_sections_for_plain_html(
    soup: BeautifulSoup,
    screen_name: str,
) -> list[ExtractedSection]:
    """
    Detect sections from HTML5 semantic elements for the plain_html format.

    Used instead of extract_sections() when no JavaScript/JSX is available.
    Delegates to html_parser.extract_semantic_sections() for DOM traversal,
    then converts each raw dict into a typed ExtractedSection.
    """
    raw_sections = extract_semantic_sections(soup)
    if not raw_sections:
        logger.debug("section_extractor: %s → no semantic sections detected", screen_name)
        return []

    sections: list[ExtractedSection] = []
    for idx, raw in enumerate(raw_sections):
        name = raw.get("name", raw.get("tag", "Section").capitalize())
        html = raw.get("html", "")

        # Extract texts: headings and visible text nodes from the HTML snippet
        texts = _extract_texts_from_html(html)

        # index is included in the id so same-named sections stay unique
        sections.append(ExtractedSection.create_semantic(
            screen=screen_name,
            name=name,
            index=idx,
            texts=texts[:10],
            jsx_snippet=html[:2_000],
        ))

    logger.debug(
        "section_extractor: %s → %d sections via semantic detection",
        screen_name, len(sections),
    )
    # Semantic sections use a relaxed quality check: presence of HTML content is sufficient
    return [s for s in sections if s.jsx_snippet.strip() or s.texts]


def _detect_by_semantic(
    soup: BeautifulSoup,
    screen_name: str,
) -> list[ExtractedSection]:
    """Internal alias used by tests and the coordinator for semantic strategy."""
    return extract_sections_for_plain_html(soup, screen_name)


def _extract_texts_from_html(html: str) -> list[str]:
    """Extract visible text strings from an HTML snippet (no JS required)."""
    try:
        soup = BeautifulSoup(html, "html.parser")
        texts: list[str] = []
        seen: set[str] = set()
        for tag in soup.find_all(["h1", "h2", "h3", "h4", "p", "a", "button", "span"]):
            text = tag.get_text(strip=True)
            if text and len(text) > 2 and text not in seen:
                seen.add(text)
                texts.append(text)
        return texts[:10]
    except Exception:
        return []
