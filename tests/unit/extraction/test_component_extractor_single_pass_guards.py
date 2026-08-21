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
from design_graph.extraction.component_extractor import extract_component
from design_graph.parsing.js_parser import find_all_boundaries


def _boundary(js: str, name: str):
    bounds = find_all_boundaries(js)
    return next(b for b in bounds if b.name == name)


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

    def test_focus_with_empty_value_after_clean_produces_no_interaction(self):
        # '' cleans to an empty string — must be skipped, not recorded as a
        # focus interaction with a blank to_val.
        js = """
        function EmptyFocusInput() {
          return (
            <input onFocus={e => e.target.style.borderColor = ''} />
          );
        }
        """
        b = _boundary(js, "EmptyFocusInput")
        comp = extract_component(js, b, 1, {})
        assert not any(i.trigger == "focus" for i in comp.interactions)

    def test_focus_interactions_capped_at_max(self):
        focus_count = MAX_INTERACTIONS_PER_COMPONENT + 3
        handlers = "\n".join(
            f'<input key={{{i}}} onFocus={{e => e.target.style.prop{i} = "val{i}"}} />'
            for i in range(focus_count)
        )
        js = f"""
        function FocusHeavy() {{
          return (
            <div>
              {handlers}
            </div>
          );
        }}
        """
        b = _boundary(js, "FocusHeavy")
        comp = extract_component(js, b, 1, {})
        assert len(comp.interactions) <= MAX_INTERACTIONS_PER_COMPONENT


# ── extract_component: state-toggle hover/focus (C13/T25) edge cases ─────────

class TestStateToggleEdgeCases:
    def test_focus_state_toggle_ternary_captured(self):
        # setFocused(true) inside onFocus (not onMouseEnter/Leave) — the
        # elif branch that classifies a state toggle as trigger="focus".
        js = """
        function SearchField() {
            const [focused, setFocused] = useState(false);
            return (
                <input
                    onFocus={() => setFocused(true)}
                    onBlur={() => setFocused(false)}
                    style={{ borderColor: focused ? C.accent : C.border }}
                />
            );
        }
        """
        b = _boundary(js, "SearchField")
        comp = extract_component(js, b, 1, {})
        focus = next((i for i in comp.interactions if i.trigger == "focus"), None)
        assert focus is not None
        assert focus.css_prop == "borderColor"
        assert focus.to_val == "C.accent"

    def test_state_ternary_with_empty_branch_produces_no_interaction(self):
        js = """
        function EmptyTernaryBranch() {
            const [hov, setHov] = useState(false);
            return (
                <div onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
                    style={{ color: hov ? '' : 'red' }}>
                    content
                </div>
            );
        }
        """
        b = _boundary(js, "EmptyTernaryBranch")
        comp = extract_component(js, b, 1, {})
        assert not any(i.css_prop == "color" for i in comp.interactions)

    def test_state_toggle_loop_stops_when_cap_already_reached(self):
        # Interactions already at MAX from imperative hover mutations before
        # the state-toggle block even runs — its first cap check must break
        # immediately, adding nothing more.
        hover_count = MAX_INTERACTIONS_PER_COMPONENT
        handlers = "\n".join(
            f'<div key={{{i}}} onMouseEnter={{e => e.target.style.prop{i} = "a{i}"}} '
            f'onMouseLeave={{e => e.target.style.prop{i} = "b{i}"}} />'
            for i in range(hover_count)
        )
        js = f"""
        function CapReachedBeforeState() {{
            const [hov, setHov] = useState(false);
            return (
                <div onMouseEnter={{() => setHov(true)}} onMouseLeave={{() => setHov(false)}}>
                    {handlers}
                    <span style={{{{ color: hov ? C.red : C.border }}}} />
                </div>
            );
        }}
        """
        b = _boundary(js, "CapReachedBeforeState")
        comp = extract_component(js, b, 1, {})
        assert len(comp.interactions) == MAX_INTERACTIONS_PER_COMPONENT
        assert not any(i.css_prop == "color" for i in comp.interactions)

    def test_ternary_loop_stops_at_cap_mid_component(self):
        # Cap has room for exactly one more interaction when the ternary
        # loop starts — its own inner cap check must stop after the first
        # property, not the outer state/setter loop's check.
        hover_count = MAX_INTERACTIONS_PER_COMPONENT - 1
        handlers = "\n".join(
            f'<div key={{{i}}} onMouseEnter={{e => e.target.style.prop{i} = "a{i}"}} '
            f'onMouseLeave={{e => e.target.style.prop{i} = "b{i}"}} />'
            for i in range(hover_count)
        )
        js = f"""
        function TernaryCapMidComponent() {{
            const [hov, setHov] = useState(false);
            return (
                <div onMouseEnter={{() => setHov(true)}} onMouseLeave={{() => setHov(false)}}
                    style={{{{
                        border: hov ? C.red : C.border,
                        background: hov ? C.dark : C.light,
                    }}}}>
                    {handlers}
                </div>
            );
        }}
        """
        b = _boundary(js, "TernaryCapMidComponent")
        comp = extract_component(js, b, 1, {})
        assert len(comp.interactions) == MAX_INTERACTIONS_PER_COMPONENT


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


# sanitize_jsx's typed-marker behaviour is covered by
# tests/unit/extraction/test_jsx_sanitizer.py — child_refs derivation from
# those markers (extract_component's responsibility) stays here.

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


class TestVersionedComponentChildRef:
    def test_jsx_tag_with_trailing_digit_recognized_as_child_ref(self):
        js = """
function ItemsPageV6() {
    return (
        <div><ItemCardV6 item={x} /></div>
    );
}
"""
        comp = extract_component(js, _boundary(js, "ItemsPageV6"), 1, {})
        assert "ItemCardV6" in comp.child_refs


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


# ── Native-tag pseudo-class CSS resolution (C24/T45) ──────────────────────────
#
# input:focus { ... } is resolved by which native HTML tag the component
# itself renders, not by className — css_class_resolver.extract_tag_pseudo_rules
# feeds this, separately from rule_map (className-keyed, C10).

class TestTagPseudoClassResolutionInExtractor:
    def _boundary(self, name: str, js: str) -> FunctionBoundary:
        bounds = find_all_boundaries(js)
        return next(b for b in bounds if b.name == name)

    def test_focus_style_added_for_matching_native_tag(self):
        js = 'function NumInput() { return <input type="number" />; }'
        b = self._boundary("NumInput", js)
        tag_rule_map = {"input": {"focus": [CssRule("input:focus", "border-color", "#FFB81C")]}}
        comp = extract_component(js, b, 1, {}, tag_rule_map=tag_rule_map)
        focus_styles = {s.property: s.value for s in comp.styles if s.state == "focus"}
        assert focus_styles.get("border-color") == "#FFB81C"

    def test_non_matching_tag_is_unaffected(self):
        js = 'function Card() { return <div className="card" />; }'
        b = self._boundary("Card", js)
        tag_rule_map = {"input": {"focus": [CssRule("input:focus", "border-color", "#FFB81C")]}}
        comp = extract_component(js, b, 1, {}, tag_rule_map=tag_rule_map)
        assert not any(s.state == "focus" for s in comp.styles)

    def test_multiple_tags_sharing_one_rule_each_resolve_independently(self):
        js = """
        function LoginForm() {
            return (
                <form>
                    <input type="text" />
                    <select></select>
                </form>
            );
        }
        """
        b = self._boundary("LoginForm", js)
        tag_rule_map = {
            "input":  {"focus": [CssRule("input:focus", "outline", "none")]},
            "select": {"focus": [CssRule("select:focus", "outline", "none")]},
        }
        comp = extract_component(js, b, 1, {}, tag_rule_map=tag_rule_map)
        assert sum(1 for s in comp.styles if s.property == "outline" and s.state == "focus") == 2

    def test_no_tag_rule_map_leaves_extraction_unaffected(self):
        js = 'function NumInput() { return <input type="number" />; }'
        b = self._boundary("NumInput", js)
        comp = extract_component(js, b, 1, {}, tag_rule_map=None)
        assert not any(s.state == "focus" for s in comp.styles)


# ── Style object spread resolution (C24/T46) ──────────────────────────────────
#
# style={{...inputStyle, width: 34}} silently dropped the ...inputStyle
# token — real properties defined on the shared `inputStyle` object were
# invisible to the component's own spec.

class TestStyleSpreadResolution:
    def _boundary(self, name: str, js: str) -> FunctionBoundary:
        bounds = find_all_boundaries(js)
        return next(b for b in bounds if b.name == name)

    def test_spread_reference_properties_are_resolved(self):
        js = """
        const inputStyle = { height: 34, padding: '0 12px' };
        function NumInput() {
            return <input style={{...inputStyle, width: 34}} />;
        }
        """
        b = self._boundary("NumInput", js)
        comp = extract_component(js, b, 1, {})
        props = {s.property: s.value for s in comp.styles}
        assert props.get("height") == "34"
        assert props.get("padding") == "0 12px"
        assert props.get("width") == "34"

    def test_local_property_overrides_spread_property(self):
        js = """
        const inputStyle = { width: 30 };
        function NumInput() {
            return <input style={{...inputStyle, width: 34}} />;
        }
        """
        b = self._boundary("NumInput", js)
        comp = extract_component(js, b, 1, {})
        widths = [s.value for s in comp.styles if s.property == "width"]
        assert widths == ["34"]

    def test_unresolvable_spread_does_not_break_extraction(self):
        js = """
        function NumInput() {
            return <input style={{...missingStyle, width: 34}} />;
        }
        """
        b = self._boundary("NumInput", js)
        comp = extract_component(js, b, 1, {})
        props = {s.property: s.value for s in comp.styles}
        assert props.get("width") == "34"

    def test_no_spread_present_is_unaffected(self):
        js = 'function Card() { return <div style={{color: "red"}} />; }'
        b = self._boundary("Card", js)
        comp = extract_component(js, b, 1, {})
        props = {s.property: s.value for s in comp.styles}
        assert props.get("color") == "red"


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
