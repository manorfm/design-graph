"""Tests for parsing/css_class_resolver.py — C10.

Covers:
  - extract_css_rules: simple selectors, multi-class, ignores non-class selectors
  - resolve_classes: Tailwind built-ins, custom rule_map, custom overrides built-in
  - Guardrail G1: css_class_resolver must not import from extraction/graph/mcp
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from design_graph.parsing.css_class_resolver import (
    CssRule,
    extract_css_rules,
    resolve_classes,
)


# ── extract_css_rules ─────────────────────────────────────────────────────────

class TestExtractCssRules:
    def test_simple_class_selector_parsed(self):
        css = ".btn { display: flex; padding: 8px; }"
        rules = extract_css_rules(css)
        assert "btn" in rules
        props = {r.property: r.value for r in rules["btn"]}
        assert props["display"] == "flex"
        assert props["padding"] == "8px"

    def test_multiple_class_selectors(self):
        css = ".flex { display: flex; } .hidden { display: none; }"
        rules = extract_css_rules(css)
        assert "flex" in rules
        assert "hidden" in rules

    def test_ignores_element_selectors(self):
        css = "div { margin: 0; } p { color: red; } .card { padding: 16px; }"
        rules = extract_css_rules(css)
        assert "div" not in rules
        assert "p" not in rules
        assert "card" in rules

    def test_ignores_id_selectors(self):
        css = "#header { background: blue; } .section { flex: 1; }"
        rules = extract_css_rules(css)
        assert "header" not in rules
        assert "section" in rules

    def test_ignores_pseudo_classes(self):
        css = ".btn:hover { background: red; } .btn { background: blue; }"
        rules = extract_css_rules(css)
        # Only .btn without pseudo-class should appear
        assert "btn" in rules
        props = {r.property: r.value for r in rules["btn"]}
        assert props.get("background") == "blue"

    def test_empty_css_returns_empty_dict(self):
        assert extract_css_rules("") == {}

    def test_whitespace_only_returns_empty_dict(self):
        assert extract_css_rules("   \n\t  ") == {}

    def test_malformed_css_does_not_raise(self):
        result = extract_css_rules("this is not css {{{{")
        assert isinstance(result, dict)

    def test_returns_dict_keyed_by_class_name(self):
        css = ".primary { color: #ffb81c; font-weight: 700; }"
        rules = extract_css_rules(css)
        assert "primary" in rules
        assert isinstance(rules["primary"], list)
        assert all(isinstance(r, CssRule) for r in rules["primary"])

    def test_multiple_properties_per_class(self):
        css = ".card { display: flex; padding: 16px; border-radius: 8px; }"
        rules = extract_css_rules(css)
        props = {r.property for r in rules["card"]}
        assert {"display", "padding", "border-radius"}.issubset(props)

    def test_css_rule_selector_contains_dot_prefix(self):
        css = ".my-class { color: red; }"
        rules = extract_css_rules(css)
        rule = rules["my-class"][0]
        assert rule.selector == ".my-class"

    def test_hyphenated_class_names_parsed(self):
        css = ".bg-primary { background-color: #ffb81c; }"
        rules = extract_css_rules(css)
        assert "bg-primary" in rules


# ── resolve_classes ───────────────────────────────────────────────────────────

class TestResolveClasses:
    def test_tailwind_flex_resolved(self):
        entries = resolve_classes("flex", {})
        props = {e.property: e.value for e in entries}
        assert props.get("display") == "flex"

    def test_tailwind_gap_4_resolved(self):
        entries = resolve_classes("gap-4", {})
        props = {e.property: e.value for e in entries}
        assert props.get("gap") == "1rem"

    def test_tailwind_rounded_lg_resolved(self):
        entries = resolve_classes("rounded-lg", {})
        props = {e.property: e.value for e in entries}
        assert props.get("border-radius") == "0.5rem"

    def test_multiple_tailwind_classes(self):
        entries = resolve_classes("flex items-center gap-4", {})
        props = {e.property: e.value for e in entries}
        assert props.get("display") == "flex"
        assert props.get("align-items") == "center"
        assert props.get("gap") == "1rem"

    def test_unknown_class_produces_no_entries(self):
        entries = resolve_classes("unknown-class-xyz-123", {})
        assert entries == []

    def test_custom_rule_map_resolved(self):
        rule_map = {"btn": [CssRule(".btn", "display", "flex")]}
        entries = resolve_classes("btn", rule_map)
        props = {e.property: e.value for e in entries}
        assert props.get("display") == "flex"

    def test_custom_rule_overrides_tailwind_builtin(self):
        # .flex defined differently in custom CSS
        rule_map = {"flex": [CssRule(".flex", "display", "grid")]}
        entries = resolve_classes("flex", rule_map)
        props = {e.property: e.value for e in entries}
        assert props["display"] == "grid"

    def test_element_field_encodes_class_name(self):
        entries = resolve_classes("flex", {})
        for e in entries:
            assert "flex" in e.element

    def test_state_is_default_for_all_entries(self):
        entries = resolve_classes("flex gap-4 rounded", {})
        for e in entries:
            assert e.state == "default"

    def test_empty_class_string_returns_empty(self):
        assert resolve_classes("", {}) == []

    def test_whitespace_only_string_returns_empty(self):
        assert resolve_classes("   ", {}) == []

    def test_no_duplicate_property_from_same_class(self):
        entries = resolve_classes("flex flex", {})
        props = [e.property for e in entries]
        assert props.count("display") <= 1

    def test_each_entry_has_unique_id(self):
        entries = resolve_classes("flex items-center gap-4", {})
        ids = [e.id for e in entries]
        assert len(ids) == len(set(ids))


# ── Guardrail G1: parsing layer isolation ────────────────────────────────────

# ── Tailwind numeric sizing classes ──────────────────────────────────────────

class TestTailwindNumericWidthHeight:
    """w-{n} and h-{n} must resolve to rem values using the Tailwind spacing scale."""

    def _styles(self, cls: str) -> dict[str, str]:
        from design_graph.parsing.css_class_resolver import resolve_classes
        entries = resolve_classes(cls, {})
        return {e.property: e.value for e in entries}

    @pytest.mark.parametrize("cls,expected_value", [
        ("w-4",  "1rem"),
        ("w-8",  "2rem"),
        ("w-16", "4rem"),
        ("w-64", "16rem"),
        ("h-4",  "1rem"),
        ("h-8",  "2rem"),
        ("h-48", "12rem"),
        ("w-0",  "0px"),
        ("h-0",  "0px"),
    ])
    def test_width_height_resolves_to_rem(self, cls, expected_value):
        styles = self._styles(cls)
        prop = "width" if cls.startswith("w-") else "height"
        assert prop in styles, f"{cls!r} did not resolve any '{prop}' property"
        assert styles[prop] == expected_value, (
            f"{cls!r}: expected {prop}={expected_value!r}, got {styles[prop]!r}"
        )

    def test_half_step_w_2_resolves(self):
        styles = self._styles("w-2")
        assert styles.get("width") == "0.5rem"

    def test_fractional_key_w_05_resolves(self):
        styles = self._styles("w-0.5")
        assert styles.get("width") == "0.125rem"


class TestTailwindNumericSpacing:
    """p-{n}, m-{n}, gap-{n} and directional variants must resolve correctly."""

    def _styles(self, cls: str) -> dict[str, str]:
        from design_graph.parsing.css_class_resolver import resolve_classes
        entries = resolve_classes(cls, {})
        return {e.property: e.value for e in entries}

    @pytest.mark.parametrize("cls,prop,expected", [
        ("p-4",    "padding",        "1rem"),
        ("px-4",   "padding-left",   "1rem"),
        ("py-2",   "padding-top",    "0.5rem"),
        ("pt-6",   "padding-top",    "1.5rem"),
        ("pb-8",   "padding-bottom", "2rem"),
        ("m-4",    "margin",         "1rem"),
        ("mx-auto","margin-left",    "auto"),
        ("gap-4",  "gap",            "1rem"),
        ("gap-x-2","column-gap",     "0.5rem"),
        ("gap-y-6","row-gap",        "1.5rem"),
    ])
    def test_spacing_resolves(self, cls, prop, expected):
        styles = self._styles(cls)
        assert prop in styles, f"{cls!r} did not produce property {prop!r}"
        assert styles[prop] == expected


class TestTailwindGridClasses:
    """grid-cols-{n}, col-span-{n}, row-span-{n} must resolve to CSS grid properties."""

    def _styles(self, cls: str) -> dict[str, str]:
        from design_graph.parsing.css_class_resolver import resolve_classes
        entries = resolve_classes(cls, {})
        return {e.property: e.value for e in entries}

    @pytest.mark.parametrize("n", [1, 2, 3, 4, 6, 12])
    def test_grid_cols_resolves(self, n):
        styles = self._styles(f"grid-cols-{n}")
        assert "grid-template-columns" in styles
        assert f"repeat({n}" in styles["grid-template-columns"]

    @pytest.mark.parametrize("n", [1, 2, 3, 4, 6, 12])
    def test_col_span_resolves(self, n):
        styles = self._styles(f"col-span-{n}")
        assert "grid-column" in styles
        assert str(n) in styles["grid-column"]

    @pytest.mark.parametrize("n", [1, 2, 3, 6])
    def test_row_span_resolves(self, n):
        styles = self._styles(f"row-span-{n}")
        assert "grid-row" in styles
        assert str(n) in styles["grid-row"]


class TestTailwindMaxWidth:
    """max-w-{size} semantic classes must resolve to max-width values."""

    def _styles(self, cls: str) -> dict[str, str]:
        from design_graph.parsing.css_class_resolver import resolve_classes
        entries = resolve_classes(cls, {})
        return {e.property: e.value for e in entries}

    @pytest.mark.parametrize("cls,expected", [
        ("max-w-sm",   "24rem"),
        ("max-w-md",   "28rem"),
        ("max-w-lg",   "32rem"),
        ("max-w-xl",   "36rem"),
        ("max-w-2xl",  "42rem"),
        ("max-w-full", "100%"),
        ("max-w-none", "none"),
    ])
    def test_max_width_resolves(self, cls, expected):
        styles = self._styles(cls)
        assert "max-width" in styles, f"{cls!r} did not produce max-width"
        assert styles["max-width"] == expected


class TestTailwindNumericCoversCommonPrototypePatterns:
    """Verify realistic class strings from prototypes resolve without gaps."""

    def test_card_layout_classes_resolve(self):
        from design_graph.parsing.css_class_resolver import resolve_classes
        entries = resolve_classes("flex flex-col gap-4 p-6 rounded-lg w-full", {})
        props = {e.property for e in entries}
        assert "display" in props
        assert "gap" in props
        assert "padding" in props
        assert "width" in props

    def test_grid_layout_classes_resolve(self):
        from design_graph.parsing.css_class_resolver import resolve_classes
        entries = resolve_classes("grid grid-cols-3 gap-6 col-span-2", {})
        props = {e.property for e in entries}
        assert "grid-template-columns" in props
        assert "column-gap" in props or "gap" in props
        assert "grid-column" in props

    def test_button_sizing_classes_resolve(self):
        from design_graph.parsing.css_class_resolver import resolve_classes
        entries = resolve_classes("px-4 py-2 h-10 max-w-xs", {})
        props = {e.property for e in entries}
        assert "padding-left" in props
        assert "padding-top" in props
        assert "height" in props
        assert "max-width" in props


class TestCssClassResolverLayerIsolation:
    # Exact layer paths that parsing/ must not depend on
    FORBIDDEN_LAYERS = (
        "design_graph.extraction",
        "design_graph.graph",
        "design_graph.mcp",
    )

    def test_no_import_from_extraction_graph_mcp(self):
        src_path = pathlib.Path(
            "src/design_graph/parsing/css_class_resolver.py"
        )
        tree = ast.parse(src_path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.ImportFrom) and node.module:
                    module = node.module
                elif isinstance(node, ast.Import):
                    module = " ".join(alias.name for alias in node.names)
                else:
                    continue
                for forbidden_layer in self.FORBIDDEN_LAYERS:
                    assert not module.startswith(forbidden_layer), (
                        f"css_class_resolver.py imports from layer '{forbidden_layer}' — "
                        f"violates G1 (parsing layer isolation): {module!r}"
                    )
