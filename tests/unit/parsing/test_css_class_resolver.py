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
