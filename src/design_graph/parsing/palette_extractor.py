"""
Discovers a prototype's own color-palette constant.

Real prototypes centralize their color system in one module-level object —
`const C = { bg: '#404040', accent: '#ffb81c', ... }` — and every component
references it (`background: C.bg`) instead of repeating hex literals.
Without this, a design token can only be labeled from a hardcoded,
cross-prototype table (wrong the moment a hex value means something
different in this prototype than it did in whichever one the table was
written against) and a style value that's a bare `C.bg` reference can never
be matched to the token it visually resolves to. Both problems share one
root fix: find the real palette object in the source, and read directly
from it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from design_graph.core.patterns import RE_COLOR
from design_graph.parsing.js_parser import (
    find_matching_delimiter,
    is_quoted_string_literal,
    iter_object_literal_pairs,
    unwrap_quoted_literal,
)

_RE_CONST_OBJECT = re.compile(r"\bconst\s+([A-Za-z_$][\w$]*)\s*=\s*\{")

# A candidate object must clear both bars to count as "the palette" rather
# than an incidentally color-adjacent lookup table (a radius/duration scale
# is flat but numeric; a label/color catalog is flat but each value is
# itself a nested object) that happens to share the same const-object shape.
_MIN_PALETTE_ENTRIES = 4
_MIN_HEX_VALUE_RATIO = 0.6


@dataclass(frozen=True)
class PrototypePalette:
    """
    A prototype's own named color constant, resolved both directions:

    - label_for(hex): the key name the prototype's author gave that color —
      for labeling a DesignToken with what it's actually called here,
      instead of a label borrowed from an unrelated prototype's palette.
    - resolve_reference("C.bg"): the literal hex a direct member-expression
      style value points at — for folding a component's `background: C.bg`
      down to `#404040` before it's stored, so the exact-value token match
      that already links a literal color to its component can also see one
      written as a palette reference.
    """

    name: str
    hex_by_key: dict[str, str]

    def label_for(self, hex_value: str) -> str | None:
        target = hex_value.strip().lower()
        for key, value in self.hex_by_key.items():
            if value.strip().lower() == target:
                return key
        return None

    def resolve_reference(self, expression: str) -> str | None:
        prefix = f"{self.name}."
        if not expression.startswith(prefix):
            return None
        return self.hex_by_key.get(expression[len(prefix):])


def discover_prototype_palette(js: str) -> PrototypePalette | None:
    """
    Find the module-level `const NAME = { key: 'hex', ... }` most likely to
    be the prototype's shared color palette, or None if nothing qualifies.

    When more than one candidate clears the bar, the one with the most hex
    entries wins — the richest, most central palette in the file.
    """
    best: PrototypePalette | None = None

    for match in _RE_CONST_OBJECT.finditer(js):
        object_open = match.end() - 1
        object_close = find_matching_delimiter(js, object_open, "{", "}")
        if object_close is None:
            continue

        body = js[object_open + 1 : object_close - 1]
        pairs = list(iter_object_literal_pairs(body))
        hex_by_key = _hex_entries(pairs)
        if not _is_palette_shaped(total_entries=len(pairs), hex_entries=len(hex_by_key)):
            continue

        if best is None or len(hex_by_key) > len(best.hex_by_key):
            best = PrototypePalette(name=match.group(1), hex_by_key=hex_by_key)

    return best


def _hex_entries(pairs: list[tuple[str, str]]) -> dict[str, str]:
    entries: dict[str, str] = {}
    for key, raw_value in pairs:
        if not is_quoted_string_literal(raw_value):
            continue
        value = unwrap_quoted_literal(raw_value)
        if RE_COLOR.fullmatch(value.strip()):
            entries[key] = value
    return entries


def _is_palette_shaped(total_entries: int, hex_entries: int) -> bool:
    if total_entries == 0 or hex_entries < _MIN_PALETTE_ENTRIES:
        return False
    return hex_entries / total_entries >= _MIN_HEX_VALUE_RATIO
