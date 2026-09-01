"""
Detect named visual sections within a screen.

Detection strategy cascade — first that yields quality sections wins:
  1. JSX comment markers: {/* ── Name ── */}       (React / bundled_react)
  2. Structural fallback: <div> blocks with substantial padding/margin
  3. Inline-list fallback: x.map((item) => <lowercaseTag ...>...) — a list
     row that was never factored into its own named component
  4. Semantic fallback: HTML5 elements (nav/header/main/section/footer) (plain_html)

Strategy 4 is triggered via extract_sections_for_plain_html() which accepts
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
    StyleEntry,
    StyleState,
)
from design_graph.parsing.css_class_resolver import CssRule, resolve_classes
from design_graph.parsing.html_parser import extract_semantic_sections
from design_graph.parsing.js_parser import (
    find_matching_delimiter,
    iter_style_object_blocks,
    parse_object_literal_props,
)
from design_graph.core.patterns import (
    RE_CLASS_NAME,
    RE_COMP_REF,
    RE_JSX_RAW_LIST_HEAD,
    RE_JSX_ROW_CLASS_NAME,
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
    rule_map: dict[str, list[CssRule]] | None = None,
) -> list[ExtractedSection]:
    """
    Extract named sections from a screen's return block.
    Tries comment detection, then structural detection, then inline-list
    detection, in that order. Returns an empty list if nothing qualifies.

    rule_map: optional CSS class resolver map from
    css_class_resolver.extract_css_rules(). When provided, a section's
    className strings resolve into additional default-state styles, kept
    in ExtractedSection.element_styles (one entry per selector) — the same
    resolution extract_component already applies, needed here because this
    prototype convention styles containers via CSS classes, not inline
    style={{}} objects. Only unconditional (non-@media) rules are resolved:
    StyleEntry has no media axis populated here, so folding a viewport-
    conditional value in would silently conflate it with the unconditional
    one (the exact bug C35 fixed for components by keeping them apart via
    StyleEntry.media).
    """
    if boundary.end <= boundary.start:
        return []

    window = js[boundary.start : boundary.end]

    sections = _detect_by_comments(window, screen.name, rule_map)
    if sections:
        logger.debug(
            "section_extractor: %s → %d sections via comments",
            screen.name, len(sections),
        )
        return _apply_quality_filter(sections)

    sections = _detect_by_structure(window, screen.name, rule_map)
    if sections:
        logger.debug(
            "section_extractor: %s → %d sections via structural fallback",
            screen.name, len(sections),
        )
        return _apply_quality_filter(sections)

    sections = _detect_by_list_markup(window, screen.name, rule_map)
    if sections:
        logger.debug(
            "section_extractor: %s → %d sections via inline-list fallback",
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


def _detect_by_comments(
    window: str, screen_name: str, rule_map: dict[str, list[CssRule]] | None = None,
) -> list[ExtractedSection]:
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
            rule_map=rule_map,
        ))

    return sections


# ── Strategy 2: Structural fallback (padding-heavy divs) ──────────────────────

_PADDING_RE = re.compile(
    r'style=\{\{[^}]*(?:padding|margin)\s*:\s*["\']?(\d+)px'
)
_DIV_OPEN_RE = re.compile(r"<div\b")
_DIV_CLASS_RE = re.compile(r'<div\b[^>]*\bclassName=(["\'])([^"\']+)\1')
_PX_TOKEN_RE = re.compile(r'(\d+)px')
_DIV_CLOSE = "</div>"


def _max_px(value: str) -> int:
    """Largest `Npx` token in a CSS value — handles a shorthand like
    `26px var(--pad) 60px` where more than one side has its own length."""
    tokens = _PX_TOKEN_RE.findall(value)
    return max((int(t) for t in tokens), default=0)


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


def _literal_padding_candidates(window: str) -> list[tuple[int, int]]:
    """<div> blocks with a literal `style={{padding|margin: Npx}}` >= threshold."""
    candidates: list[tuple[int, int]] = []
    for m in _PADDING_RE.finditer(window):
        try:
            px = int(m.group(1))
        except ValueError:
            continue
        if px >= _STRUCTURAL_PADDING_THRESHOLD:
            # Capture the enclosing block: from the nearest '<div' before this match
            div_start = window.rfind("<div", 0, m.start())
            if div_start >= 0:
                candidates.append((div_start, _find_balanced_div_end(window, div_start)))
    return candidates


def _resolved_class_padding_candidates(
    window: str, rule_map: dict[str, list[CssRule]] | None,
) -> list[tuple[int, int]]:
    """
    <div className="..."> blocks whose CSS-class-resolved padding/margin
    meets the structural threshold.

    A prototype convention that styles containers exclusively via CSS
    classes (never inline style={{}}) is invisible to
    _literal_padding_candidates no matter how much padding the class
    actually carries — confirmed real case: toToggle's `.page`/`.page-head`
    have real padding/margin only in the stylesheet, so a screen like
    UsersView (no section comments, and its only `.map()` already produces
    a named component, so Strategy 3 doesn't apply either) landed on zero
    sections despite substantial real chrome (see docs/changes/C37).
    """
    if rule_map is None:
        return []
    candidates: list[tuple[int, int]] = []
    for m in _DIV_CLASS_RE.finditer(window):
        entries = resolve_classes(m.group(2), rule_map)
        qualifies = any(
            entry.state == StyleState.DEFAULT
            and entry.property.startswith(("padding", "margin"))
            and _max_px(entry.value) >= _STRUCTURAL_PADDING_THRESHOLD
            for entry in entries
        )
        if qualifies:
            candidates.append((m.start(), _find_balanced_div_end(window, m.start())))
    return candidates


def _detect_by_structure(
    window: str, screen_name: str, rule_map: dict[str, list[CssRule]] | None = None,
) -> list[ExtractedSection]:
    """
    Find <div> blocks with padding >= threshold (literal or CSS-class-
    resolved) as section separators.
    Returns at most MAX_SECTIONS_FROM_STRUCTURAL_FALLBACK sections.
    """
    candidate_positions = sorted(
        _literal_padding_candidates(window) + _resolved_class_padding_candidates(window, rule_map),
        key=lambda pair: pair[0],
    )

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
            rule_map=rule_map,
        ))

    return sections


# ── Strategy 3: Inline-list fallback (raw-markup .map() rows) ────────────────

def _list_row_label(block: str, fallback_index: int) -> str:
    """
    A human-readable name for a raw-markup list row, derived from its own
    root className (e.g. "audit-item" -> "Audit item"). Falls back to a
    positional label when the row carries no static className, mirroring
    _detect_by_structure's own "Section{i+1}" fallback for the same reason:
    a name is still needed even when the markup gives none.
    """
    match = RE_JSX_ROW_CLASS_NAME.search(block)
    if not match:
        return f"List{fallback_index + 1}"
    words = match.group(1).replace("_", "-").split("-")
    return " ".join([words[0].capitalize(), *words[1:]])


def _detect_by_list_markup(
    window: str, screen_name: str, rule_map: dict[str, list[CssRule]] | None = None,
) -> list[ExtractedSection]:
    """
    Find `x.map((item[, i]) => (<lowercaseTag ...>` — a list row rendered as
    raw JSX markup that was never factored into its own named component
    (contrast RE_JSX_LIST_HEAD, which only matches a `<Component` call and is
    handled by jsx_sanitizer instead). Each match becomes its own Section,
    bounded to its own `{...}` expression via find_matching_delimiter — the
    same balanced scan jsx_sanitizer relies on to bound `{[list:Component]}`
    markers. Reuses MAX_SECTIONS_FROM_STRUCTURAL_FALLBACK as its own cap —
    same purpose (bound a fallback strategy's output), no reason for a
    second constant.
    """
    sections: list[ExtractedSection] = []
    cursor = 0
    for match in RE_JSX_RAW_LIST_HEAD.finditer(window):
        if match.start() < cursor:
            continue  # nested inside a .map() this same pass already claimed
        if len(sections) >= MAX_SECTIONS_FROM_STRUCTURAL_FALLBACK:
            break
        region_end = find_matching_delimiter(window, match.start(), "{", "}")
        if region_end is None:
            continue  # unbalanced — leave the raw text untouched rather than guess
        block = window[match.start():region_end]
        sections.append(_build_section(
            block=block,
            sec_name=_list_row_label(block, fallback_index=len(sections)),
            screen_name=screen_name,
            detection_method=DetectionMethod.LIST_ITEM,
            rule_map=rule_map,
        ))
        cursor = region_end

    return sections


# ── Section builder ───────────────────────────────────────────────────────────

def _resolve_section_element_styles(
    block: str, rule_map: dict[str, list[CssRule]] | None,
) -> list[StyleEntry]:
    """
    Default-state styles resolved from every className string found anywhere
    in this section's block, the same way extract_component resolves a
    component's classes — needed because a prototype styling containers via
    CSS classes (not inline style={{}}) would otherwise leave a Section with
    structure but no real visual styling.

    Unlike a literal style={{}} object (which carries no selector identity —
    see ExtractedSection.styles), a className string IS the selector, and
    resolve_classes() already tags each StyleEntry with it (element=
    "class:<name>") — that attribution is preserved here, not collapsed into
    a flat dict, so two different classes contributing the same CSS property
    (e.g. .audit-item{display:grid} and .audit-dot{display:flex}) survive as
    two distinct entries instead of one silently overwriting the other (see
    docs/changes/C36).

    Returns [] when rule_map is None (caller opted out) or the block carries
    no static className. Hover/focus-state class variants (`hover:bg-red-
    500`) are skipped: a section has no rendered "state" to put them in.
    """
    if rule_map is None:
        return []
    seen_classes: set[str] = set()
    classes: list[str] = []
    for m in RE_CLASS_NAME.finditer(block):
        for cls in m.group(1).split():
            if cls not in seen_classes:
                seen_classes.add(cls)
                classes.append(cls)
    if not classes:
        return []
    return [
        entry for entry in resolve_classes(" ".join(classes), rule_map)
        if entry.state == StyleState.DEFAULT
    ]


def _build_section(
    block: str,
    sec_name: str,
    screen_name: str,
    detection_method: DetectionMethod,
    rule_map: dict[str, list[CssRule]] | None = None,
) -> ExtractedSection:
    # Literal style={{}} objects — no selector identity, attributed to the
    # section as a whole (see ExtractedSection.styles). CSS-class-resolved
    # styles go in element_styles instead, one entry per selector (C36).
    styles: dict[str, str] = {}
    for style_block in iter_style_object_blocks(block):
        for prop, val in parse_object_literal_props(style_block):
            if val and val not in ("true", "false", "null", "undefined"):
                styles[prop] = val
    element_styles = _resolve_section_element_styles(block, rule_map)

    # Component references — first-appearance order, not alphabetical (C34,
    # same fix C30 already applied to a component's own child_refs).
    seen_comp_refs: set[str] = set()
    comp_refs: list[str] = []
    for pattern in (RE_JSX_TAG, RE_COMP_REF):
        for m in pattern.finditer(block):
            name = m.group(1)
            if len(name) >= 3 and name not in seen_comp_refs:
                seen_comp_refs.add(name)
                comp_refs.append(name)

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
        component_refs=comp_refs,
        texts=texts,
        jsx_snippet=block[:3_000].strip(),
        detection_method=detection_method,
        element_styles=element_styles,
    )


# ── Quality filter ────────────────────────────────────────────────────────────

def _qualifies(section: ExtractedSection) -> bool:
    return (
        len(section.component_refs) >= 1
        or len(section.texts) >= 2
        or len(section.styles) + len(section.element_styles) >= 3
    )


def _apply_quality_filter(sections: list[ExtractedSection]) -> list[ExtractedSection]:
    return [s for s in sections if _qualifies(s)]


# ── Strategy 4: Semantic detection (plain HTML) ───────────────────────────────

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
