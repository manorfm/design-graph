"""
Arbitrary data a specific component's own body references by name from a
module-level constant — e.g. an icon-name -> SVG-path lookup table
(`const ICONS = {...}`, indexed by the `Icon` component's own `name` prop)
or a role-key -> badge metadata table (`const ROLE_META = {...}`, indexed
by `RoleBadge`'s `role` prop).

No attempt is made to understand *how* the component uses the reference
(`ICONS[name]` vs a switch statement vs anything else) — only whether the
constant's own name appears as a token inside the component's body. That's
a deliberate, purely mechanical rule: the alternative ("this component
looks like it wraps an icon library") is exactly the heuristic
docs/changes/C32 already tried and rejected as fragile and overfit to a
couple of known icon libraries. Capturing the referenced constant's own
literal content verbatim needs no such guess — an agent reconstructing
`Icon` gets the exact same lookup table the prototype itself renders from,
not a resolved guess at what any entry in it means (see docs/changes/C39).

Only statically-quoted string values are captured (the same boundary
component_extractor.py's own inline-style handling and
module_text_extractor.py already draw): a computed value, spread, or bare
identifier reference can't be rendered as "the same data" without
evaluating JS, so it's left out rather than guessed at.
"""

from __future__ import annotations

import re

from design_graph.parsing.js_parser import (
    is_quoted_string_literal,
    iter_object_literal_pairs,
    split_top_level,
    unwrap_quoted_literal,
)

# A role/status metadata table nested one level (`root: { label: 'Root' }`)
# is the deepest real shape found so far (docs/changes/C39) — deep enough
# for that, without open-ended recursion into whatever a future prototype
# might nest arbitrarily deep.
_MAX_NESTED_DEPTH = 1

JsonValue = str | dict[str, "JsonValue"] | list["JsonValue"]


def extract_referenced_module_data(
    component_body: str, module_constants: dict[str, str],
) -> dict[str, JsonValue]:
    """
    Every module_constants entry whose NAME appears as a whole-word token
    inside component_body, converted to a JSON-safe structure of string
    values only (see _literal_to_jsonable). Empty after conversion (no
    statically-quoted string reachable within the depth bound) is omitted
    rather than stored as `{}`/`[]` noise.

    module_constants: the same {name: raw_literal} map
    parsing.js_parser.find_module_level_constants() produces for the whole
    file — computed once per build, not once per component, and passed
    down (see pipeline/coordinator.py).
    """
    referenced: dict[str, JsonValue] = {}
    for name, literal in module_constants.items():
        if re.search(rf"\b{re.escape(name)}\b", component_body) is None:
            continue
        value = _literal_to_jsonable(literal, depth=0)
        if value:
            referenced[name] = value
    return referenced


def _literal_to_jsonable(raw: str, depth: int) -> JsonValue | None:
    raw = raw.strip()
    if is_quoted_string_literal(raw):
        return unwrap_quoted_literal(raw)

    if raw.startswith("{") and raw.endswith("}"):
        obj: dict[str, JsonValue] = {}
        for key, raw_value in iter_object_literal_pairs(raw[1:-1]):
            value = _literal_to_jsonable(raw_value, depth + 1) if depth <= _MAX_NESTED_DEPTH else None
            if value is not None:
                obj[key] = value
        return obj or None

    if raw.startswith("[") and raw.endswith("]"):
        items: list[JsonValue] = []
        for element in split_top_level(raw[1:-1]):
            element = element.strip()
            if not element:
                continue
            value = _literal_to_jsonable(element, depth + 1) if depth <= _MAX_NESTED_DEPTH else None
            if value is not None:
                items.append(value)
        return items or None

    return None
