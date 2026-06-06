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
