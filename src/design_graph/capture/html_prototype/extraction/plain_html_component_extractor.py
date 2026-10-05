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
  - model/graph/writer.py → persists entities to Kuzu (model layer)
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from design_graph.model.entities import ComponentType, ExtractedComponent, StyleEntry
from design_graph.capture.html_prototype.sources import DOMPattern, SemanticType

logger = logging.getLogger(__name__)

# Mapping from html_parser semantic types to graph component types
_SEMANTIC_TYPE_TO_COMP_TYPE: dict[SemanticType, ComponentType] = {
    SemanticType.CARD:      ComponentType.CARD,
    SemanticType.NAV:       ComponentType.NAVIGATION,
    SemanticType.MODAL:     ComponentType.MODAL,
    SemanticType.BADGE:     ComponentType.BADGE,
    SemanticType.FORM:      ComponentType.FORM,
    SemanticType.TABLE:     ComponentType.TABLE,
    SemanticType.LIST_ITEM: ComponentType.LIST_ITEM,
    SemanticType.HEADER:    ComponentType.COMPONENT,
    SemanticType.FOOTER:    ComponentType.COMPONENT,
    SemanticType.COMPONENT: ComponentType.COMPONENT,
}

# CSS class attribute extractor
_CLASS_ATTR_RE = re.compile(r'class="([^"]+)"')


def dom_pattern_to_extracted_component(pattern: DOMPattern) -> ExtractedComponent:
    """
    Convert a single DOMPattern into an ExtractedComponent.

    The ExtractedComponent represents a repeating DOM structure as if it
    were a named React component — same schema, different origin.
    """
    comp_type  = _SEMANTIC_TYPE_TO_COMP_TYPE.get(pattern.semantic_type, ComponentType.COMPONENT)
    source_code = pattern.first_example
    classes    = _extract_css_classes(source_code)
    styles     = _extract_inline_styles(source_code, pattern.inferred_name)

    logger.debug(
        "plain_html_extractor: %s (type=%s, count=%d, classes=%s)",
        pattern.inferred_name, comp_type, pattern.count, classes[:40],
    )

    return ExtractedComponent(
        name=pattern.inferred_name,
        comp_type=comp_type,
        source_code=source_code,
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
        return m.group(1).strip()
    return ""


def _extract_inline_styles(html_snippet: str, comp_name: str) -> list[StyleEntry]:
    """
    Every CSS declaration on the component's own root element.

    A nested descendant (e.g. a decorative <span class="dot"> inside a
    <button>) may carry its own style="..."; attributing a child's styling
    to the component itself is exactly how Chip's 7px status dot ended up
    in the component's own "Styles — default" table, as if the button were
    a 7px circle — so only the root's attribute is read.
    """
    root = BeautifulSoup(html_snippet, "html.parser").find(True)
    styles: list[StyleEntry] = []
    seen_props: set[str] = set()
    for declaration in (root.get("style") or "").split(";") if root else []:
        prop, sep, value = declaration.partition(":")
        prop, value = prop.strip(), value.strip()
        if sep and prop and value and prop not in seen_props:
            seen_props.add(prop)
            styles.append(StyleEntry.create(element=comp_name, property=prop, value=value))
    return styles
