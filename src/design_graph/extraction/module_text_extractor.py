"""
UI copy embedded in module-level constant arrays and objects.

Real prototypes routinely define shared config as a top-level array of
object literals — `const DETAIL_TABS = [{ key, label, icon, desc }, ...]`
— rendered later via `.map()` or passed as a prop (`<K.Tabs items={DETAIL_TABS}
.../>`). Just as routinely, the same convention shows up as a plain object
instead of an array — `const ROLE_META = { root: { label: 'Root', ... },
admin: { label: 'Admin', ... } }` — keyed by an identifier (a role, a
status) rather than positioned in a list. No existing extractor visits
either shape: component and section extraction only scan inside function
boundaries (find_all_boundaries), and a shared, hoisted constant like this
sits outside every one of them by construction. Its `label`/`desc` strings
are exactly the kind of content an agent searches for by name — this
module is the only place that makes them findable at all.
"""

from __future__ import annotations

from design_graph.core.models import FunctionBoundary, TextEntry, TextType
from design_graph.parsing.js_parser import (
    find_module_level_constants,
    is_quoted_string_literal,
    iter_object_literal_pairs,
    split_top_level,
    unwrap_quoted_literal,
)

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

# ROLE_META-style nesting (`root: { label: 'Root', ... }`) is one level of
# object-inside-object — deeper nesting has no evidence behind it yet (see
# docs/changes/C39), so this stays a fixed depth rather than open recursion.
_MAX_NESTED_OBJECT_DEPTH = 1


def extract_module_level_texts(js: str, all_boundaries: list[FunctionBoundary]) -> list[TextEntry]:
    """
    UI text from every `const NAME = [...]` or `const NAME = {...}`
    declared outside all function boundaries.

    Declarations inside a function boundary are skipped on purpose (already
    handled by find_module_level_constants): that text is already visible
    to RE_UI_STRING's per-component sweep (component_extractor scans a
    function's whole body, not just its JSX), so indexing it again here
    under the constant's name instead of the component's would just
    produce a duplicate result with a less useful source.
    """
    texts: list[TextEntry] = []
    seen_ids: set[str] = set()

    for constant_name, literal in find_module_level_constants(js, all_boundaries).items():
        if literal.startswith("["):
            entries = _extract_array_entries(literal[1:-1], constant_name)
        elif literal.startswith("{"):
            entries = _extract_object_entries(literal[1:-1], constant_name)
        else:
            entries = []
        for entry in entries:
            if entry.id not in seen_ids:
                seen_ids.add(entry.id)
                texts.append(entry)

    return texts


def _extract_copy_pairs(obj_body: str, constant_name: str, depth: int) -> list[TextEntry]:
    """
    UI copy from one object literal's own top-level `key: value` pairs.

    A value that's itself a quoted string becomes a TextEntry (typed by its
    key, defaulting to LABEL — the same rule the array-of-objects path
    already applied). A value that's itself a nested object literal
    (`root: { label: 'Root', ... }`) is walked one level deeper, up to
    _MAX_NESTED_OBJECT_DEPTH — deep enough for the real ROLE_META-shaped
    config this was written against, without open-ended recursion into
    whatever shape a future prototype might nest.
    """
    entries: list[TextEntry] = []
    for key, raw_value in iter_object_literal_pairs(obj_body):
        if is_quoted_string_literal(raw_value):
            content = unwrap_quoted_literal(raw_value).strip()
            if TextEntry.is_plausible_content(content):
                entries.append(TextEntry.create(
                    content=content,
                    text_type=_TEXT_TYPE_BY_PROPERTY_NAME.get(key, TextType.LABEL),
                    source=constant_name,
                ))
        elif depth < _MAX_NESTED_OBJECT_DEPTH and raw_value.startswith("{") and raw_value.endswith("}"):
            entries.extend(_extract_copy_pairs(raw_value[1:-1], constant_name, depth + 1))
    return entries


def _extract_array_entries(array_body: str, constant_name: str) -> list[TextEntry]:
    entries: list[TextEntry] = []
    for element in split_top_level(array_body):
        element = element.strip()
        if element.startswith("{") and element.endswith("}"):
            entries.extend(_extract_copy_pairs(element[1:-1], constant_name, depth=0))
    return entries


def _extract_object_entries(obj_body: str, constant_name: str) -> list[TextEntry]:
    return _extract_copy_pairs(obj_body, constant_name, depth=0)
