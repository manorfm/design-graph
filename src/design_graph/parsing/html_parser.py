"""
DOM analysis for plain HTML prototypes.

Two main analyses:
1. extract_dom_patterns  — finds DOM structures that repeat >= N times.
   Each repetition is a candidate reusable component.
2. extract_semantic_sections — uses HTML5 semantic elements and headings
   to identify named sections within a page.

No JS or graph access — pure BeautifulSoup analysis.
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict

from bs4 import BeautifulSoup, Tag

from design_graph.core.constants import (
    LAYOUT_ONLY_TAGS,
    MIN_DOM_PATTERN_REPETITIONS,
    MIN_DOM_SIGNATURE_LENGTH,
)
from design_graph.core.models import DOMPattern

logger = logging.getLogger(__name__)

# HTML5 semantic elements that identify top-level sections
_SEMANTIC_SECTION_TAGS: tuple[str, ...] = (
    "nav", "header", "main", "aside", "section", "article", "footer",
)

# DOM structure → inferred component name mapping
_STRUCTURE_TO_COMPONENT_NAME: list[tuple[tuple[str, ...], str]] = [
    (("img", "h3", "p", "button"), "Card"),
    (("img", "h2", "p"),           "FeaturedCard"),
    (("img", "h3", "p"),           "MediaCard"),
    (("input", "button"),          "SearchBar"),
    (("th",),                      "DataTable"),
    (("li",),                      "ListItem"),
    (("h1",),                      "PageHeader"),
    (("label", "input"),           "FormField"),
]


# ── Public API ────────────────────────────────────────────────────────────────

def extract_dom_patterns(
    soup: BeautifulSoup,
    min_count: int = MIN_DOM_PATTERN_REPETITIONS,
) -> list[DOMPattern]:
    """
    Detect DOM structures that appear at least min_count times.
    Returns patterns sorted by repetition count descending.
    """
    sig_counter: Counter[str] = Counter()
    sig_first_tag: dict[str, Tag] = {}

    try:
        for tag in soup.find_all(True):
            if not isinstance(tag, Tag):
                continue
            if tag.name in LAYOUT_ONLY_TAGS:
                continue

            sig = _structure_signature(tag)
            if len(sig) < MIN_DOM_SIGNATURE_LENGTH:
                continue

            sig_counter[sig] += 1
            if sig not in sig_first_tag:
                sig_first_tag[sig] = tag
    except Exception as exc:  # noqa: BLE001
        logger.warning("extract_dom_patterns: traversal error: %s", exc)
        return []

    patterns: list[DOMPattern] = []
    for sig, count in sig_counter.most_common():
        if count < min_count:
            continue

        first_tag = sig_first_tag[sig]
        html_snippet = str(first_tag)[:600]
        inferred_name = _infer_component_name(sig, first_tag)
        semantic_type = _infer_semantic_type(first_tag)

        patterns.append(DOMPattern(
            signature=sig,
            count=count,
            first_example=html_snippet,
            inferred_name=inferred_name,
            semantic_type=semantic_type,
        ))

    logger.debug("extract_dom_patterns: found %d patterns (min_count=%d)", len(patterns), min_count)
    return patterns


def extract_semantic_sections(soup: BeautifulSoup) -> list[dict]:
    """
    Extract named sections from HTML5 semantic elements.
    Returns a list of dicts with keys: name, tag, html, depth.
    """
    sections: list[dict] = []

    try:
        for tag in soup.find_all(_SEMANTIC_SECTION_TAGS):
            if not isinstance(tag, Tag):
                continue

            name = _section_name_from_tag(tag)
            html_content = str(tag)[:2000]

            sections.append({
                "name": name,
                "tag":  tag.name,
                "html": html_content,
                "depth": len(list(tag.parents)),
            })
    except Exception as exc:  # noqa: BLE001
        logger.warning("extract_semantic_sections: error: %s", exc)
        return []

    logger.debug("extract_semantic_sections: found %d sections", len(sections))
    return sections


# ── Private helpers ───────────────────────────────────────────────────────────

def _structure_signature(tag: Tag, depth: int = 0, max_depth: int = 3) -> str:
    """
    Generate a structural signature for a DOM element.
    Includes tag name, first CSS class hint, and immediate children (up to depth 3).
    Text content is excluded — only structure matters.
    """
    if depth >= max_depth:
        return tag.name

    children = [c for c in tag.children if isinstance(c, Tag) and c.name]
    classes = tag.get("class", [])
    cls_hint = f".{classes[0]}" if classes else ""
    base = f"{tag.name}{cls_hint}"

    if not children:
        return base

    child_sigs = ",".join(
        _structure_signature(c, depth + 1, max_depth) for c in children[:6]
    )
    return f"{base}>{child_sigs}"


def _infer_component_name(sig: str, tag: Tag) -> str:
    """
    Map a DOM structure signature to a PascalCase component name.
    Falls back to capitalising the tag name if no mapping matches.
    """
    sig_lower = sig.lower()
    child_tags = {c.name for c in tag.find_all(True)}

    for required_children, name in _STRUCTURE_TO_COMPONENT_NAME:
        if all(t in child_tags for t in required_children):
            return name

    # Use first CSS class as a name hint
    classes = tag.get("class", [])
    if classes:
        raw = classes[0].replace("-", " ").replace("_", " ").title().replace(" ", "")
        if raw and raw[0].isupper():
            return raw

    # Fall back to tag name in PascalCase
    return tag.name.capitalize() + "Component"


def _infer_semantic_type(tag: Tag) -> str:
    """Infer a broad semantic category from the tag's name and class."""
    name = tag.name.lower()
    classes_str = " ".join(tag.get("class", [])).lower()

    if name == "nav" or "nav" in classes_str or "navbar" in classes_str:
        return "nav"
    if name in ("header", "footer"):
        return name
    if "card" in classes_str or "tile" in classes_str:
        return "card"
    if "modal" in classes_str or "dialog" in classes_str:
        return "modal"
    if "badge" in classes_str or "tag" in classes_str:
        return "badge"
    if name in ("form",) or "form" in classes_str:
        return "form"
    if name in ("table", "thead", "tbody"):
        return "table"
    if name == "li" or "item" in classes_str:
        return "list-item"
    return "component"


def _section_name_from_tag(tag: Tag) -> str:
    """
    Derive a human-readable section name from a semantic tag.
    Priority: first heading > id attribute > tag name.
    """
    heading = tag.find(re.compile(r"^h[1-6]$"))
    if heading:
        text = heading.get_text(strip=True)
        if text:
            return text[:60]

    tag_id = tag.get("id", "")
    if tag_id:
        return str(tag_id).replace("-", " ").replace("_", " ").title()

    aria_label = tag.get("aria-label", "")
    if aria_label:
        return str(aria_label)[:60]

    return tag.name.capitalize()
