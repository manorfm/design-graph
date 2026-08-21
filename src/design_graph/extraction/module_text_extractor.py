"""
UI copy embedded in module-level constant arrays.

Real prototypes routinely define shared config as a top-level array of
object literals — `const DETAIL_TABS = [{ key, label, icon, desc }, ...]`
— rendered later via `.map()` or passed as a prop (`<K.Tabs items={DETAIL_TABS}
.../>`). No existing extractor visits this text: component and section
extraction only scan inside function boundaries (find_all_boundaries), and
a shared, hoisted constant like this sits outside every one of them by
construction. Its `label`/`desc` strings are exactly the kind of content an
agent searches for by name — this module is the only place that makes them
findable at all.
"""

from __future__ import annotations

import re

from design_graph.core.models import FunctionBoundary, TextEntry, TextType
from design_graph.parsing.js_parser import (
    find_matching_delimiter,
    is_quoted_string_literal,
    iter_object_literal_pairs,
    split_top_level,
    unwrap_quoted_literal,
)

# SCREAMING_CASE is the same convention real prototypes already use for
# shared, hoisted config — it doubles as the filter for "this is a copy
# catalog", not an incidental local array a lowercase/camelCase name would
# suggest.
_RE_MODULE_CONSTANT_ARRAY = re.compile(r"\bconst\s+([A-Z][A-Z0-9_]*)\s*=\s*\[")

_TEXT_TYPE_BY_PROPERTY_NAME: dict[str, TextType] = {
    "label":       TextType.LABEL,
    "title":       TextType.HEADING,
    "heading":     TextType.HEADING,
    "desc":        TextType.DESCRIPTION,
    "description": TextType.DESCRIPTION,
    "subtitle":    TextType.DESCRIPTION,
    "hint":        TextType.DESCRIPTION,
    "placeholder": TextType.PLACEHOLDER,
}


def extract_module_level_texts(js: str, all_boundaries: list[FunctionBoundary]) -> list[TextEntry]:
    """
    UI text from every `const NAME = [{ ... }, ...]` declared outside all
    function boundaries.

    Declarations inside a function boundary are skipped on purpose: that
    text is already visible to RE_UI_STRING's per-component sweep
    (component_extractor scans a function's whole body, not just its JSX),
    so indexing it again here under the constant's name instead of the
    component's would just produce a duplicate result with a less useful
    source.
    """
    texts: list[TextEntry] = []
    seen_ids: set[str] = set()

    for match in _RE_MODULE_CONSTANT_ARRAY.finditer(js):
        if _is_inside_any_boundary(match.start(), all_boundaries):
            continue

        constant_name = match.group(1)
        array_open = match.end() - 1
        array_close = find_matching_delimiter(js, array_open, "[", "]")
        if array_close is None:
            continue

        array_body = js[array_open + 1 : array_close - 1]
        for entry in _extract_entries(array_body, constant_name):
            if entry.id not in seen_ids:
                seen_ids.add(entry.id)
                texts.append(entry)

    return texts


def _is_inside_any_boundary(position: int, boundaries: list[FunctionBoundary]) -> bool:
    return any(b.start <= position < b.end for b in boundaries)


def _extract_entries(array_body: str, constant_name: str) -> list[TextEntry]:
    entries: list[TextEntry] = []
    for element in split_top_level(array_body):
        element = element.strip()
        if not (element.startswith("{") and element.endswith("}")):
            continue
        for key, raw_value in iter_object_literal_pairs(element[1:-1]):
            if not is_quoted_string_literal(raw_value):
                continue
            content = unwrap_quoted_literal(raw_value).strip()
            if not TextEntry.is_plausible_content(content):
                continue
            entries.append(TextEntry.create(
                content=content,
                text_type=_TEXT_TYPE_BY_PROPERTY_NAME.get(key, TextType.LABEL),
                source=constant_name,
            ))
    return entries
