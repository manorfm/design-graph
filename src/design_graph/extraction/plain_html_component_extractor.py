"""
Convert DOM patterns from html_parser into ExtractedComponent objects.

This module bridges the parsing layer (html_parser.DOMPattern) and the
graph write layer (GraphWriter.write_component) for the plain_html format.

Plain HTML prototypes have no React functions — their repeating DOM patterns
serve as the "component" abstraction. A <div class="card"> repeating 4 times
becomes a component named by _infer_component_name() in html_parser.

Responsibility boundary:
  - html_parser.py   → detects repeating DOM patterns (parsing layer)
  - THIS module      → converts patterns to domain entities (extraction layer)
  - graph/writer.py  → persists entities to Kuzu (graph layer)
"""

from __future__ import annotations

import hashlib
import logging
import re

from design_graph.core.models import DOMPattern, ExtractedComponent, StyleEntry

logger = logging.getLogger(__name__)

# Mapping from html_parser semantic types to graph component types
_SEMANTIC_TYPE_TO_COMP_TYPE: dict[str, str] = {
    "card":       "card",
    "nav":        "navigation",
    "modal":      "modal",
    "badge":      "badge",
    "form":       "form",
    "table":      "table",
    "list-item":  "list-item",
    "header":     "component",
    "footer":     "component",
    "component":  "component",
}

# Inline style pattern: property: value (CSS, not JSX)
_CSS_INLINE_STYLE_RE = re.compile(
    r'([\w-]+)\s*:\s*([^;,"\'}{>\n]{2,60}?)(?:;|(?=\s*[\w-]+\s*:)|\s*$)',
    re.MULTILINE,
)

# CSS class attribute extractor
_CLASS_ATTR_RE = re.compile(r'class="([^"]+)"')


def dom_pattern_to_extracted_component(pattern: DOMPattern) -> ExtractedComponent:
    """
    Convert a single DOMPattern into an ExtractedComponent.

    The ExtractedComponent represents a repeating DOM structure as if it
    were a named React component — same schema, different origin.
    """
    comp_type  = _SEMANTIC_TYPE_TO_COMP_TYPE.get(pattern.semantic_type, "component")
    jsx_snippet = pattern.first_example[:3_000]
    classes    = _extract_css_classes(jsx_snippet)
    styles     = _extract_inline_styles(jsx_snippet, pattern.inferred_name)

    logger.debug(
        "plain_html_extractor: %s (type=%s, count=%d, classes=%s)",
        pattern.inferred_name, comp_type, pattern.count, classes[:40],
    )

    return ExtractedComponent(
        name=pattern.inferred_name,
        comp_type=comp_type,
        jsx_snippet=jsx_snippet,
        occurrence=pattern.count,
        classes=classes,
        styles=styles,
        interactions=[],    # plain HTML has no hover/focus JS handlers
        texts=[],           # texts not extracted at this layer
        child_refs=[],      # no JSX child component references
    )


def dom_patterns_to_extracted_components(
    patterns: list[DOMPattern],
) -> list[ExtractedComponent]:
    """
    Convert a list of DOMPatterns to ExtractedComponents, deduplicating by name.

    When two patterns produce the same inferred_name, the one with the higher
    count is kept. This mirrors the deduplication guarantee in GraphWriter.
    """
    if not patterns:
        return []

    seen_names: dict[str, int] = {}   # name → index in result
    result: list[ExtractedComponent] = []

    for pattern in patterns:
        comp = dom_pattern_to_extracted_component(pattern)
        if comp.name in seen_names:
            # Keep the one with the higher occurrence count
            existing_idx = seen_names[comp.name]
            if comp.occurrence > result[existing_idx].occurrence:
                result[existing_idx] = comp
            logger.debug(
                "plain_html_extractor: deduplicated %s (kept count=%d)",
                comp.name, result[existing_idx].occurrence,
            )
        else:
            seen_names[comp.name] = len(result)
            result.append(comp)

    logger.info(
        "plain_html_extractor: converted %d patterns → %d unique components",
        len(patterns), len(result),
    )
    return result


# ── private helpers ───────────────────────────────────────────────────────────

def _extract_css_classes(html_snippet: str) -> str:
    """Extract the first CSS class list found in the HTML snippet."""
    m = _CLASS_ATTR_RE.search(html_snippet)
    if m:
        classes = m.group(1).strip()
        return classes[:120]
    return ""


def _extract_inline_styles(html_snippet: str, comp_name: str) -> list[StyleEntry]:
    """
    Extract CSS inline style properties from the HTML snippet.
    Returns at most 20 style entries to match the component_extractor cap.
    """
    styles: list[StyleEntry] = []
    seen_props: set[str] = set()

    style_attr_re = re.compile(r'style="([^"]{5,400})"')
    for style_match in style_attr_re.finditer(html_snippet):
        css_block = style_match.group(1)
        for prop_match in _CSS_INLINE_STYLE_RE.finditer(css_block):
            prop  = prop_match.group(1).strip()
            value = prop_match.group(2).strip()
            if not prop or not value or prop in seen_props:
                continue
            seen_props.add(prop)
            sid = hashlib.md5(f"{comp_name}_{prop}_{value}".encode()).hexdigest()[:8]
            styles.append(StyleEntry(
                id=f"st_{sid}",
                element=comp_name,
                state="default",
                property=prop,
                value=value,
            ))
            if len(styles) >= 20:
                break
        if len(styles) >= 20:
            break

    return styles
