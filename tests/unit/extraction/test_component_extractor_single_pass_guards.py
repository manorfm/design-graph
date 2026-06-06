"""
Tests for single-pass extraction guards in component_extractor.py.

Targets the specific branches not covered:
  - sanitize_jsx: style block 200-400 chars (returns unchanged, line 95)
  - extract_component: falsy/reserved style values skipped (line 143)
  - extract_component: MAX_INTERACTIONS cap hit (line 160)
  - extract_component: focus interactions via RE_ON_FOCUS (lines 180-185)
  - extract_component: text filter — too short, too long, lowercase-only, #/rgba (194-196)
"""

from __future__ import annotations

import pytest

from design_graph.core.constants import MAX_INTERACTIONS_PER_COMPONENT
from design_graph.extraction.component_extractor import extract_component, sanitize_jsx
from design_graph.parsing.js_parser import find_all_boundaries


def _boundary(js: str, name: str):
    bounds = find_all_boundaries(js)
    return next(b for b in bounds if b.name == name)


# ── sanitize_jsx: medium-length style block (200-400 chars) ──────────────────

class TestSanitizeJsxMediumStyle:
    def test_style_between_200_and_400_chars_returned_unchanged(self):
        # Build style={{...}} where inner is 200-299 chars.
        # The style regex fires (≥ 200 chars) but RE_LONG_TERNARY does NOT (< 300).
        # _collapse_long_style takes the `return inner` branch (line 95).
        inner = ", ".join(f"prop{i}: '{10 + i}px'" for i in range(12))
        # Pad to land between 200-299 chars
        while len(inner) < 200:
            inner += ", extraFillProp: '1px'"
        assert 200 <= len(inner) <= 299, f"Need 200-299 chars, got {len(inner)}"
        jsx = "style={{" + inner + "}}"
        result = sanitize_jsx(jsx)
        # _collapse_long_style returns unchanged (line 95 taken), RE_LONG_TERNARY skips (<300)
        assert "..." not in result
        assert "prop0" in result or "extraFillProp" in result

    def test_style_above_400_chars_collapsed(self):
        inner = ", ".join(f"propNameLong{i}: 'veryLongValue{i}px'" for i in range(18))
        jsx = "style={{" + inner + "}}"
        assert len(inner) > 400
        result = sanitize_jsx(jsx)
        assert "..." in result


# ── extract_component: reserved/empty style values skipped ───────────────────

class TestStyleValueFiltering:
    def _make_js(self, style_value: str) -> str:
        return f"""
        function BtnTest() {{
          return <button style={{{{color: '{style_value}'}}}}>Click</button>;
        }}
        """

    @pytest.mark.parametrize("val", ["", "true", "false", "null", "undefined", "inherit"])
    def test_reserved_style_value_not_in_extracted_styles(self, val):
        js = self._make_js(val)
        b  = _boundary(js, "BtnTest")
        comp = extract_component(js, b, 1, {})
        values = {s.value for s in comp.styles}
        assert val not in values


# ── extract_component: MAX_INTERACTIONS cap ───────────────────────────────────

class TestInteractionCap:
    def test_interactions_capped_at_max(self):
        hover_count = MAX_INTERACTIONS_PER_COMPONENT + 3
        handlers = "\n".join(
            f"onMouseEnter={{e => e.target.style.prop{i} = 'val{i}'}}\n"
            f"onMouseLeave={{e => e.target.style.prop{i} = 'orig{i}'}}"
            for i in range(hover_count)
        )
        js = f"""
        function HoverHeavy() {{
          return (
            <div
              {handlers}
            >content</div>
          );
        }}
        """
        b = _boundary(js, "HoverHeavy")
        comp = extract_component(js, b, 1, {})
        assert len(comp.interactions) <= MAX_INTERACTIONS_PER_COMPONENT


# ── extract_component: focus interactions ────────────────────────────────────

class TestFocusInteractions:
    def test_onfocus_handler_produces_focus_interaction(self):
        js = """
        function InputField() {
          return (
            <input
              style={{borderColor: '#4a5568'}}
              onFocus={e => e.target.style.borderColor = '#ffb81c'}
            />
          );
        }
        """
        b = _boundary(js, "InputField")
        comp = extract_component(js, b, 1, {})
        focus_interactions = [i for i in comp.interactions if i.trigger == "focus"]
        assert len(focus_interactions) >= 1

    def test_focus_interaction_has_css_prop_and_to_val(self):
        js = """
        function SearchInput() {
          return (
            <input
              onFocus={e => e.target.style.outline = '2px solid #ffb81c'}
            />
          );
        }
        """
        b = _boundary(js, "SearchInput")
        comp = extract_component(js, b, 1, {})
        for inter in comp.interactions:
            if inter.trigger == "focus":
                assert inter.css_prop
                assert inter.to_val
                return


# ── extract_component: text filtering ────────────────────────────────────────

class TestTextFiltering:
    def test_text_shorter_than_3_chars_excluded(self):
        # "OK" is 2 chars — below 3-char minimum
        js = """
        function BtnShort() {
          return <button>"OK"</button>;
        }
        """
        b = _boundary(js, "BtnShort")
        comp = extract_component(js, b, 1, {})
        texts = [t.content for t in comp.texts]
        assert "OK" not in texts

    def test_text_longer_than_80_chars_excluded(self):
        long_text = "A" * 85
        js = f"""
        function BtnLong() {{
          return <button>"{long_text}"</button>;
        }}
        """
        b = _boundary(js, "BtnLong")
        comp = extract_component(js, b, 1, {})
        texts = [t.content for t in comp.texts]
        assert long_text not in texts

    def test_lowercase_only_text_excluded(self):
        js = """
        function BtnLower() {
          return <button>"lowercase_only"</button>;
        }
        """
        b = _boundary(js, "BtnLower")
        comp = extract_component(js, b, 1, {})
        texts = [t.content for t in comp.texts]
        assert "lowercase_only" not in texts

    def test_hex_color_text_excluded(self):
        js = """
        function BtnHex() {
          return <button>"#ffb81c"</button>;
        }
        """
        b = _boundary(js, "BtnHex")
        comp = extract_component(js, b, 1, {})
        texts = [t.content for t in comp.texts]
        assert "#ffb81c" not in texts


# ── Truncation logging ────────────────────────────────────────────────────────

import logging

from design_graph.core.constants import (
    MAX_CLASSES_PER_COMPONENT,
    MAX_STYLES_PER_COMPONENT,
    MAX_TEXTS_PER_COMPONENT,
)


def _make_js_with_many_styles(name: str, count: int) -> str:
    style_blocks = " ".join(
        f'style={{{{prop{i}: "val{i}px"}}}}'
        for i in range(count)
    )
    return f"function {name}() {{ return <div {style_blocks} />; }}"


# ── CSS class rule_map integration (C10) ─────────────────────────────────────

from design_graph.core.models import FunctionBoundary
from design_graph.parsing.css_class_resolver import CssRule, resolve_classes


# ── JSX typed markers (C11) ──────────────────────────────────────────────────

class TestSanitizeJsxTypedMarkers:
    """Verify sanitize_jsx replaces dynamic JSX with typed markers."""

    def test_map_render_gets_list_marker(self):
        jsx = "<ul>{items.map(item => <CartItem key={item.id} />)}</ul>"
        result = sanitize_jsx(jsx)
        assert "[list:CartItem]" in result

    def test_short_circuit_gets_conditional_marker(self):
        jsx = "<div>{isOpen && <Modal />}</div>"
        result = sanitize_jsx(jsx)
        assert "[conditional:Modal]" in result

    def test_ternary_two_components_gets_either_marker(self):
        jsx = "<div>{error ? <ErrorBanner /> : <SuccessCard />}</div>"
        result = sanitize_jsx(jsx)
        assert "[either:ErrorBanner|SuccessCard]" in result

    def test_marker_uses_bracket_notation(self):
        jsx = "<div>{flag && <Sidebar />}</div>"
        result = sanitize_jsx(jsx)
        assert "{[conditional:Sidebar]}" in result

    def test_no_js_logic_exposed_after_substitution(self):
        jsx = "<div>{isLoggedIn && <UserMenu />}</div>"
        result = sanitize_jsx(jsx)
        assert "isLoggedIn" not in result
        assert "&&" not in result

    def test_map_logic_not_exposed(self):
        jsx = "<ul>{items.map(i => <ListItem />)}</ul>"
        result = sanitize_jsx(jsx)
        assert "items.map" not in result
        assert ".map(" not in result

    def test_static_text_unchanged(self):
        jsx = "<h1>Título fixo</h1>"
        assert "Título fixo" in sanitize_jsx(jsx)

    def test_handler_still_collapsed(self):
        # RE_LONG_EVENT_HANDLER requires >= 60 non-brace chars inside the handler
        flat_body = "() => handleMouseEnterEventWithLongNameAndManyParameters(event, index, itemId, extraData)"
        jsx = f'<div onMouseEnter={{{flat_body}}} />'
        result = sanitize_jsx(jsx)
        assert "on[handler]" in result
        assert "handleMouseEnter" not in result

    def test_multiple_markers_in_same_jsx(self):
        jsx = (
            "<div>"
            "{items.map(i => <Item />)}"
            "{isAdmin && <AdminPanel />}"
            "</div>"
        )
        result = sanitize_jsx(jsx)
        assert "[list:Item]" in result
        assert "[conditional:AdminPanel]" in result

    def test_component_name_preserved_in_marker(self):
        jsx = "<div>{flag && <MyComplexComponent />}</div>"
        result = sanitize_jsx(jsx)
        assert "MyComplexComponent" in result

    def test_ternary_marker_order_is_then_else(self):
        jsx = "<div>{ok ? <ThenComp /> : <ElseComp />}</div>"
        result = sanitize_jsx(jsx)
        # ThenComp must come before ElseComp in the marker
        idx_then = result.find("ThenComp")
        idx_else = result.find("ElseComp")
        assert idx_then < idx_else


class TestChildRefsFromMarkers:
    """Verify extract_component adds marker-referenced components to child_refs."""

    def _boundary(self, name: str, js: str) -> FunctionBoundary:
        bounds = find_all_boundaries(js)
        return next(b for b in bounds if b.name == name)

    def test_conditional_comp_in_child_refs(self):
        js = """
function NavBar() {
    return (
        <div>{flag && <UserMenu />}</div>
    );
}
"""
        comp = extract_component(js, self._boundary("NavBar", js), 1, {})
        assert "UserMenu" in comp.child_refs

    def test_list_comp_in_child_refs(self):
        js = """
function ItemList() {
    return (
        <ul>{items.map(i => <CartItem />)}</ul>
    );
}
"""
        comp = extract_component(js, self._boundary("ItemList", js), 1, {})
        assert "CartItem" in comp.child_refs

    def test_ternary_both_comps_in_child_refs(self):
        js = """
function StatusView() {
    return (
        <div>{ok ? <SuccessCard /> : <ErrorBanner />}</div>
    );
}
"""
        comp = extract_component(js, self._boundary("StatusView", js), 1, {})
        assert "SuccessCard" in comp.child_refs
        assert "ErrorBanner" in comp.child_refs

    def test_no_duplicates_when_marker_and_direct_tag(self):
        js = """
function CartView() {
    return (
        <div><CartItem />{items.map(i => <CartItem />)}</div>
    );
}
"""
        comp = extract_component(js, self._boundary("CartView", js), 1, {})
        assert comp.child_refs.count("CartItem") == 1


class TestCssClassResolutionInExtractor:
    """Verify extract_component uses rule_map to add StyleEntry objects."""

    def _simple_boundary(self, name: str, js: str) -> FunctionBoundary:
        bounds = find_all_boundaries(js)
        return next(b for b in bounds if b.name == name)

    def test_class_styles_added_when_rule_map_provided(self):
        js = 'function Btn() { return <button className="flex gap-4" />; }'
        b = self._simple_boundary("Btn", js)
        rule_map = {"flex": [CssRule(".flex", "display", "flex")]}
        comp = extract_component(js, b, 1, {}, rule_map=rule_map)
        props = {s.property: s.value for s in comp.styles}
        assert props.get("display") == "flex"

    def test_tailwind_builtin_resolved_when_no_custom_map(self):
        js = 'function Card() { return <div className="flex items-center" />; }'
        b = self._simple_boundary("Card", js)
        comp = extract_component(js, b, 1, {}, rule_map={})
        props = {s.property: s.value for s in comp.styles}
        assert props.get("display") == "flex"
        assert props.get("align-items") == "center"

    def test_no_class_styles_when_rule_map_is_none(self):
        js = 'function Card() { return <div className="flex gap-4" />; }'
        b = self._simple_boundary("Card", js)
        comp_no_map = extract_component(js, b, 1, {}, rule_map=None)
        comp_with_map = extract_component(js, b, 1, {}, rule_map={})
        # With no rule_map: no class styles added
        # With rule_map={}: Tailwind built-ins are resolved
        class_style_count_no_map = sum(1 for s in comp_no_map.styles if "class:" in s.element)
        class_style_count_with_map = sum(1 for s in comp_with_map.styles if "class:" in s.element)
        assert class_style_count_no_map == 0
        assert class_style_count_with_map > 0

    def test_class_styles_have_class_prefix_in_element(self):
        js = 'function Btn() { return <button className="flex" />; }'
        b = self._simple_boundary("Btn", js)
        comp = extract_component(js, b, 1, {}, rule_map={})
        class_styles = [s for s in comp.styles if s.element.startswith("class:")]
        assert len(class_styles) > 0
        for s in class_styles:
            assert s.element.startswith("class:")

    def test_inline_styles_take_precedence_over_class_capacity(self):
        from design_graph.core.constants import MAX_STYLES_PER_COMPONENT
        # Fill up styles with inline, then class styles should be capped
        inline_parts = " ".join(
            f'style={{{{prop{i}: "val{i}px"}}}}' for i in range(MAX_STYLES_PER_COMPONENT)
        )
        js = f'function BigBtn() {{ return <button {inline_parts} className="flex" />; }}'
        b = self._simple_boundary("BigBtn", js)
        comp = extract_component(js, b, 1, {}, rule_map={})
        assert len(comp.styles) <= MAX_STYLES_PER_COMPONENT


class TestTruncationLogging:
    def test_styles_cap_logged_at_debug_when_exceeded(self, caplog):
        limit = MAX_STYLES_PER_COMPONENT
        js = _make_js_with_many_styles("BigComp", limit + 5)
        b  = _boundary(js, "BigComp")
        with caplog.at_level(logging.DEBUG, logger="design_graph.extraction.component_extractor"):
            extract_component(js, b, 1, {})
        assert any("capped" in r.message.lower() or "cap" in r.message.lower()
                   for r in caplog.records), \
            "Expected a debug log mentioning cap/capped when styles exceed limit"

    def test_no_cap_log_when_styles_within_limit(self, caplog):
        js = _make_js_with_many_styles("SmallComp", 2)
        b  = _boundary(js, "SmallComp")
        with caplog.at_level(logging.DEBUG, logger="design_graph.extraction.component_extractor"):
            extract_component(js, b, 1, {})
        cap_records = [r for r in caplog.records if "capped" in r.message.lower()]
        assert not cap_records
