"""
TDD — Etapa 5a: ComponentProp extraction from React function signatures.

Tests for extract_props_from_function_signature(), which parses destructured
props from a React function signature and returns typed ComponentProp models.
"""

from __future__ import annotations

import pytest

from design_graph.core.models import ComponentProp, FunctionBoundary
from design_graph.extraction.prop_extractor import extract_props_from_function_signature


def _boundary(name: str, js: str) -> FunctionBoundary:
    """Build a FunctionBoundary spanning the full JS string."""
    return FunctionBoundary(name=name, start=0, body_start=js.index("{"), end=len(js))


class TestExtractPropsFromFunctionSignature:
    def test_extracts_required_props_with_no_default(self):
        js = "function NavBar({ title, onClose }) { return <nav/>; }"
        props = extract_props_from_function_signature(js, _boundary("NavBar", js))
        names = {p.prop_name for p in props}
        assert "title" in names
        assert "onClose" in names

    def test_required_prop_has_empty_default_value(self):
        js = "function NavBar({ title }) { return <nav/>; }"
        props = extract_props_from_function_signature(js, _boundary("NavBar", js))
        title = next(p for p in props if p.prop_name == "title")
        assert title.default_value == ""

    def test_extracts_optional_prop_with_string_default(self):
        js = "function Btn({ variant = 'primary', label }) { return <button/>; }"
        props = extract_props_from_function_signature(js, _boundary("Btn", js))
        variant = next(p for p in props if p.prop_name == "variant")
        assert "primary" in variant.default_value

    def test_extracts_optional_prop_with_boolean_default(self):
        js = "function Input({ disabled = false, value }) { return <input/>; }"
        props = extract_props_from_function_signature(js, _boundary("Input", js))
        disabled = next(p for p in props if p.prop_name == "disabled")
        assert "false" in disabled.default_value

    def test_extracts_optional_prop_with_numeric_default(self):
        js = "function Paginator({ page = 1, size = 20 }) { return <div/>; }"
        props = extract_props_from_function_signature(js, _boundary("Paginator", js))
        page = next(p for p in props if p.prop_name == "page")
        assert "1" in page.default_value

    def test_ignores_rest_spread_props(self):
        js = "function Card({ title, ...rest }) { return <div/>; }"
        props = extract_props_from_function_signature(js, _boundary("Card", js))
        names = {p.prop_name for p in props}
        assert "rest" not in names

    def test_returns_empty_for_no_props_component(self):
        js = "function Icon() { return <svg/>; }"
        props = extract_props_from_function_signature(js, _boundary("Icon", js))
        assert props == []

    def test_returns_empty_for_positional_props(self):
        """Components with positional args (not destructuring) should return empty."""
        js = "function Legacy(props) { return <div/>; }"
        props = extract_props_from_function_signature(js, _boundary("Legacy", js))
        assert props == []

    def test_prop_id_is_deterministic(self):
        js = "function NavBar({ title }) { return <nav/>; }"
        props1 = extract_props_from_function_signature(js, _boundary("NavBar", js))
        props2 = extract_props_from_function_signature(js, _boundary("NavBar", js))
        assert props1[0].id == props2[0].id

    def test_prop_id_differs_across_component_names(self):
        js_a = "function CompA({ value }) { return <div/>; }"
        js_b = "function CompB({ value }) { return <div/>; }"
        props_a = extract_props_from_function_signature(js_a, _boundary("CompA", js_a))
        props_b = extract_props_from_function_signature(js_b, _boundary("CompB", js_b))
        assert props_a[0].id != props_b[0].id

    def test_component_name_is_set_correctly(self):
        js = "function NavBar({ title }) { return <nav/>; }"
        props = extract_props_from_function_signature(js, _boundary("NavBar", js))
        assert all(p.component_name == "NavBar" for p in props)

    def test_handles_array_default_without_splitting_on_comma(self):
        """Default value [1, 2] must not split into two props."""
        js = "function List({ items = [], size }) { return <ul/>; }"
        props = extract_props_from_function_signature(js, _boundary("List", js))
        names = {p.prop_name for p in props}
        assert names == {"items", "size"}

    def test_prop_model_is_frozen(self):
        js = "function Btn({ label }) { return <button/>; }"
        props = extract_props_from_function_signature(js, _boundary("Btn", js))
        with pytest.raises(Exception):
            props[0].prop_name = "changed"  # type: ignore[misc]

    def test_typescript_type_annotation_without_default_is_skipped(self):
        """Props declared as TS annotations (prop: Type) without a default must be ignored."""
        js = "function Input({ value: string, onChange }) { return <input/>; }"
        props = extract_props_from_function_signature(js, _boundary("Input", js))
        names = {p.prop_name for p in props}
        # "value: string" is a TS annotation — should be skipped
        assert "value" not in names
        # "onChange" has no annotation and no default — should be kept
        assert "onChange" in names

    def test_uppercase_prop_name_is_skipped(self):
        """Props whose name starts with uppercase are invalid React props and must be ignored."""
        js = "function Comp({ ValidProp, normalProp }) { return <div/>; }"
        props = extract_props_from_function_signature(js, _boundary("Comp", js))
        names = {p.prop_name for p in props}
        assert "ValidProp" not in names
        assert "normalProp" in names

    def test_props_capped_at_max_per_component(self):
        """Extraction must stop at _MAX_PROPS_PER_COMPONENT regardless of how many are declared."""
        from design_graph.extraction.prop_extractor import _MAX_PROPS_PER_COMPONENT
        many = ", ".join(f"prop{i}" for i in range(_MAX_PROPS_PER_COMPONENT + 5))
        js = f"function BigComp({{ {many} }}) {{ return <div/>; }}"
        props = extract_props_from_function_signature(js, _boundary("BigComp", js))
        assert len(props) == _MAX_PROPS_PER_COMPONENT
