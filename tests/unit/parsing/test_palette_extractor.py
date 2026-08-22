"""
Tests for palette_extractor — discovers a prototype's own color-palette
constant (`const C = { bg: '#404040', accent: '#ffb81c', ... }`) instead
of relying on a hardcoded, cross-prototype label table.

Real prototypes declare many other `const NAME = { ... }` lookup tables
in the same file — radius/duration scales (numbers, not colors), nested
label/color catalogs (DIET_TAGS, ITEM_TYPES: each value is itself an
object, not a flat hex string). The fixtures below mirror exactly that
shape so the palette detector proves it can tell them apart, not just
find the one candidate handed to it.
"""

from __future__ import annotations

from design_graph.parsing.palette_extractor import PrototypePalette, discover_prototype_palette

REAL_SHAPED_JS = """
const C = {
  bg: '#404040', card: '#2a2a2a', card2: '#333333', border: '#3a3a3a', border2: '#444444',
  accent: '#FFB81C', red: '#ef4444', green: '#22c55e', blue: '#60a5fa', purple: '#a78bfa',
  text: '#ffffff', muted: '#9ca3af', faint: '#6b7280', dim: '#4b5563',
  textOnAccent: '#1a1a1a',
};
const R = { xs: 4, sm: 8, md: 10, lg: 16, xl: 24 };
const H = { sm: 28, md: 34 };
const DIET_TAGS = {
  VEGETARIAN: { label: 'Vegetariano', color: '#22c55e' },
  VEGAN:      { label: 'Vegano',      color: '#16a34a' },
};
function Chip({ on, color }) {
  return <button style={{ background: on ? color : C.card2, border: `1px solid ${C.border}` }} />;
}
"""


class TestDiscoverPrototypePalette:
    def test_finds_the_flat_hex_valued_constant(self):
        palette = discover_prototype_palette(REAL_SHAPED_JS)
        assert palette is not None
        assert palette.name == "C"

    def test_ignores_number_valued_constants(self):
        palette = discover_prototype_palette(REAL_SHAPED_JS)
        assert palette.name != "R"
        assert palette.name != "H"

    def test_ignores_nested_object_catalogs(self):
        palette = discover_prototype_palette(REAL_SHAPED_JS)
        assert palette.name != "DIET_TAGS"

    def test_captures_every_hex_entry(self):
        palette = discover_prototype_palette(REAL_SHAPED_JS)
        assert palette.hex_by_key["bg"] == "#404040"
        assert palette.hex_by_key["textOnAccent"] == "#1a1a1a"
        assert palette.hex_by_key["accent"] == "#FFB81C"

    def test_no_qualifying_constant_returns_none(self):
        js = "const R = { xs: 4, sm: 8 }; const H = { sm: 28 };"
        assert discover_prototype_palette(js) is None

    def test_empty_source_returns_none(self):
        assert discover_prototype_palette("") is None

    def test_richest_candidate_wins_when_multiple_qualify(self):
        js = """
        const SMALL = { a: '#111111', b: '#222222', c: '#333333', d: '#444444' };
        const BIG = {
          a: '#111111', b: '#222222', c: '#333333', d: '#444444',
          e: '#555555', f: '#666666', g: '#777777', h: '#888888',
        };
        """
        palette = discover_prototype_palette(js)
        assert palette.name == "BIG"

    def test_object_with_mostly_non_hex_strings_is_rejected(self):
        # Labels catalog, not a palette — most values aren't colors at all.
        js = """
        const LABELS = {
            dashboard: 'Dashboard', restaurants: 'Restaurantes', menus: 'Menus',
            categories: 'Categorias', accent: '#ffb81c',
        };
        """
        assert discover_prototype_palette(js) is None


class TestPrototypePaletteLabelFor:
    def _palette(self) -> PrototypePalette:
        return discover_prototype_palette(REAL_SHAPED_JS)

    def test_known_hex_resolves_to_its_source_key(self):
        assert self._palette().label_for("#1a1a1a") == "textOnAccent"

    def test_case_insensitive_match(self):
        assert self._palette().label_for("#FFB81C") == "accent"
        assert self._palette().label_for("#ffb81c") == "accent"

    def test_unknown_hex_returns_none(self):
        assert self._palette().label_for("#123456") is None


class TestPrototypePaletteResolveReference:
    def _palette(self) -> PrototypePalette:
        return discover_prototype_palette(REAL_SHAPED_JS)

    def test_direct_member_expression_resolves(self):
        assert self._palette().resolve_reference("C.bg") == "#404040"

    def test_unknown_key_returns_none(self):
        assert self._palette().resolve_reference("C.doesNotExist") is None

    def test_different_object_prefix_returns_none(self):
        # Not this palette's own constant — R.md is a radius token, not a color.
        assert self._palette().resolve_reference("R.md") is None

    def test_bare_identifier_without_member_access_returns_none(self):
        assert self._palette().resolve_reference("C") is None

    def test_expression_with_arithmetic_is_not_resolved(self):
        # Deliberately out of scope — a concatenation like `color + '1e'`
        # isn't a direct palette reference and shouldn't be guessed at.
        assert self._palette().resolve_reference("C.accent + '1e'") is None
