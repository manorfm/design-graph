"""Tests for token_extractor — T04."""

import pytest

from design_graph.core.models import DesignToken, RawSources
from design_graph.parsing.token_extractor import build_token_map, extract_tokens


def _sources(js: str = "", css: str = "") -> RawSources:
    return RawSources(js=js, css=css, inner_html="", html_hash="test", format="plain_html")


REPEATED_COLOR_JS = """
style={{backgroundColor: '#ffb81c'}}
style={{backgroundColor: '#ffb81c'}}
style={{backgroundColor: '#ffb81c'}}
style={{color: '#ef4444'}}
style={{color: '#ef4444'}}
"""

REPEATED_SPACING_JS = """
style={{padding: '16px'}}
style={{padding: '16px'}}
style={{padding: '16px'}}
"""


class TestExtractColors:
    def test_finds_frequently_used_color(self):
        tokens = extract_tokens(_sources(js=REPEATED_COLOR_JS))
        values = {t.value for t in tokens if t.category == "color"}
        assert "#ffb81c" in values

    def test_filters_white_variants(self):
        js = "color: '#fff'" * 5 + " color: '#ffffff'" * 5
        tokens = extract_tokens(_sources(js=js))
        values = {t.value for t in tokens}
        assert "#ffffff" not in values
        assert "#fff" not in values

    def test_filters_black_variants(self):
        js = "color: '#000'" * 5 + " color: '#000000'" * 5
        tokens = extract_tokens(_sources(js=js))
        values = {t.value for t in tokens}
        assert "#000000" not in values

    def test_single_occurrence_color_excluded(self):
        js = "color: '#aabbcc'"  # only 1×
        tokens = extract_tokens(_sources(js=js))
        assert not any(t.value == "#aabbcc" for t in tokens)

    def test_usage_reflects_occurrence_count(self):
        tokens = extract_tokens(_sources(js=REPEATED_COLOR_JS))
        primary = next((t for t in tokens if t.value == "#ffb81c"), None)
        assert primary is not None
        assert primary.usage >= 3

    def test_short_hex_normalised_to_six_digits(self):
        js = "color: '#abc'" * 3
        tokens = extract_tokens(_sources(js=js))
        values = {t.value for t in tokens}
        assert "#aabbcc" in values

    def test_known_color_gets_semantic_label(self):
        tokens = extract_tokens(_sources(js=REPEATED_COLOR_JS))
        primary = next((t for t in tokens if t.value == "#ffb81c"), None)
        assert primary is not None
        assert primary.label == "primary"

    def test_unknown_color_uses_value_as_label(self):
        js = "color: '#1a2b3c'" * 3
        tokens = extract_tokens(_sources(js=js))
        t = next((t for t in tokens if t.value == "#1a2b3c"), None)
        assert t is not None
        assert t.label == "#1a2b3c"

    def test_at_most_50_color_tokens(self):
        many = " ".join(f"'#{'%06x' % i}'" for i in range(1, 101)) * 3
        tokens = [t for t in extract_tokens(_sources(js=many)) if t.category == "color"]
        assert len(tokens) <= 50


class TestExtractSpacing:
    def test_finds_frequently_used_spacing(self):
        tokens = extract_tokens(_sources(js=REPEATED_SPACING_JS))
        categories = {t.category for t in tokens}
        assert "spacing" in categories

    def test_spacing_normalised_to_4px_grid(self):
        # 14px rounds to 16px (nearest multiple of 4)
        js = "padding: '14px'" * 3
        tokens = extract_tokens(_sources(js=js))
        spacing_values = {t.value for t in tokens if t.category == "spacing"}
        assert "16px" in spacing_values

    def test_single_occurrence_spacing_excluded(self):
        js = "padding: '7px'"  # only 1×
        tokens = extract_tokens(_sources(js=js))
        assert not any(t.value == "8px" for t in tokens)

    def test_spacing_from_css_detected(self):
        css = "padding: 16px; margin: 16px; gap: 16px;"
        tokens = extract_tokens(_sources(css=css))
        spacing = [t for t in tokens if t.category == "spacing"]
        assert len(spacing) >= 1


class TestTokenFields:
    _VALID_CATEGORIES = {"color", "spacing", "typography", "shadow", "radius", "css_var"}

    def test_all_tokens_have_required_fields(self):
        tokens = extract_tokens(_sources(js=REPEATED_COLOR_JS + REPEATED_SPACING_JS))
        for t in tokens:
            assert t.id, "id must be non-empty"
            assert t.category in self._VALID_CATEGORIES, f"unknown category: {t.category}"
            assert t.label, "label must be non-empty"
            assert t.value, "value must be non-empty"
            assert t.usage >= 1, "usage must be positive"

    def test_token_ids_are_deterministic_across_runs(self):
        sources = _sources(js=REPEATED_COLOR_JS)
        ids_a = {t.id for t in extract_tokens(sources)}
        ids_b = {t.id for t in extract_tokens(sources)}
        assert ids_a == ids_b

    def test_token_ids_are_unique_within_run(self):
        tokens = extract_tokens(_sources(js=REPEATED_COLOR_JS + REPEATED_SPACING_JS))
        ids = [t.id for t in tokens]
        assert len(ids) == len(set(ids))

    def test_returns_list_of_design_token(self):
        tokens = extract_tokens(_sources(js=REPEATED_COLOR_JS))
        for t in tokens:
            assert isinstance(t, DesignToken)


REPEATED_FONT_SIZE_JS = """
fontSize: '16px'
fontSize: '16px'
fontSize: '16px'
fontSize: '14px'
fontSize: '14px'
fontSize: '14px'
"""

REPEATED_FONT_WEIGHT_JS = """
fontWeight: '700'
fontWeight: '700'
fontWeight: '700'
fontWeight: '600'
fontWeight: '600'
fontWeight: '600'
"""


class TestExtractTypographySizes:
    def test_finds_frequently_used_font_size(self):
        tokens = extract_tokens(_sources(js=REPEATED_FONT_SIZE_JS))
        values = {t.value for t in tokens if t.category == "typography"}
        assert "16px" in values

    def test_finds_multiple_distinct_sizes(self):
        tokens = extract_tokens(_sources(js=REPEATED_FONT_SIZE_JS))
        values = {t.value for t in tokens if t.category == "typography"}
        assert "14px" in values

    def test_single_occurrence_font_size_excluded(self):
        js = "fontSize: '22px'"  # 1× only
        tokens = extract_tokens(_sources(js=js))
        assert not any(t.value == "22px" and t.category == "typography" for t in tokens)

    def test_font_size_gets_semantic_label(self):
        tokens = extract_tokens(_sources(js=REPEATED_FONT_SIZE_JS))
        t16 = next((t for t in tokens if t.value == "16px" and t.category == "typography"), None)
        assert t16 is not None
        assert t16.label == "text_base"

    def test_font_size_14_gets_text_sm_label(self):
        tokens = extract_tokens(_sources(js=REPEATED_FONT_SIZE_JS))
        t14 = next((t for t in tokens if t.value == "14px" and t.category == "typography"), None)
        assert t14 is not None
        assert t14.label == "text_sm"

    def test_font_size_from_css_detected(self):
        css = "font-size: 18px; font-size: 18px; font-size: 18px;"
        tokens = extract_tokens(_sources(css=css))
        values = {t.value for t in tokens if t.category == "typography"}
        assert "18px" in values

    def test_typography_token_has_deterministic_id(self):
        sources = _sources(js=REPEATED_FONT_SIZE_JS)
        ids_a = {t.id for t in extract_tokens(sources) if t.category == "typography"}
        ids_b = {t.id for t in extract_tokens(sources) if t.category == "typography"}
        assert ids_a == ids_b

    def test_out_of_range_font_size_excluded(self):
        # 200px is too large to be a text size token
        js = "fontSize: '200px'" * 3
        tokens = extract_tokens(_sources(js=js))
        assert not any(t.value == "200px" for t in tokens)


class TestExtractTypographyWeights:
    def test_finds_frequently_used_weight(self):
        tokens = extract_tokens(_sources(js=REPEATED_FONT_WEIGHT_JS))
        values = {t.value for t in tokens if t.category == "typography"}
        assert "700" in values

    def test_weight_700_gets_bold_label(self):
        tokens = extract_tokens(_sources(js=REPEATED_FONT_WEIGHT_JS))
        t = next((t for t in tokens if t.value == "700" and t.category == "typography"), None)
        assert t is not None
        assert t.label == "weight_bold"

    def test_weight_600_gets_semibold_label(self):
        tokens = extract_tokens(_sources(js=REPEATED_FONT_WEIGHT_JS))
        t = next((t for t in tokens if t.value == "600" and t.category == "typography"), None)
        assert t is not None
        assert t.label == "weight_semibold"

    def test_bold_keyword_extracted(self):
        js = "fontWeight: 'bold'" * 3
        tokens = extract_tokens(_sources(js=js))
        t = next((t for t in tokens if t.value == "bold" and t.category == "typography"), None)
        assert t is not None
        assert t.label == "weight_bold"

    def test_single_occurrence_weight_excluded(self):
        js = "fontWeight: '300'"  # 1× only
        tokens = extract_tokens(_sources(js=js))
        assert not any(t.value == "300" and t.category == "typography" for t in tokens)

    def test_weight_from_css_detected(self):
        css = "font-weight: 500; font-weight: 500; font-weight: 500;"
        tokens = extract_tokens(_sources(css=css))
        values = {t.value for t in tokens if t.category == "typography"}
        assert "500" in values


REPEATED_SHADOW_JS = """
boxShadow: '0 2px 8px rgba(0,0,0,0.15)'
boxShadow: '0 2px 8px rgba(0,0,0,0.15)'
boxShadow: '0 2px 8px rgba(0,0,0,0.15)'
boxShadow: '0 4px 16px rgba(0,0,0,0.25)'
boxShadow: '0 4px 16px rgba(0,0,0,0.25)'
boxShadow: '0 4px 16px rgba(0,0,0,0.25)'
"""


class TestExtractShadows:
    def test_finds_frequently_used_shadow(self):
        tokens = extract_tokens(_sources(js=REPEATED_SHADOW_JS))
        cats = {t.category for t in tokens}
        assert "shadow" in cats

    def test_finds_multiple_distinct_shadows(self):
        tokens = extract_tokens(_sources(js=REPEATED_SHADOW_JS))
        shadow_tokens = [t for t in tokens if t.category == "shadow"]
        assert len(shadow_tokens) >= 2

    def test_single_occurrence_shadow_excluded(self):
        js = "boxShadow: '0 1px 2px rgba(0,0,0,0.1)'"  # 1× only
        tokens = extract_tokens(_sources(js=js))
        assert not any(t.category == "shadow" for t in tokens)

    def test_shadow_value_preserved(self):
        tokens = extract_tokens(_sources(js=REPEATED_SHADOW_JS))
        values = {t.value for t in tokens if t.category == "shadow"}
        assert any("0 2px 8px" in v for v in values)

    def test_shadow_label_is_shadow_n(self):
        tokens = extract_tokens(_sources(js=REPEATED_SHADOW_JS))
        shadow_tokens = [t for t in tokens if t.category == "shadow"]
        for t in shadow_tokens:
            assert t.label.startswith("shadow_")

    def test_shadow_from_css_detected(self):
        css = "box-shadow: 0 1px 4px #000; " * 3
        tokens = extract_tokens(_sources(css=css))
        assert any(t.category == "shadow" for t in tokens)

    def test_shadow_token_ids_are_deterministic(self):
        sources = _sources(js=REPEATED_SHADOW_JS)
        ids_a = {t.id for t in extract_tokens(sources) if t.category == "shadow"}
        ids_b = {t.id for t in extract_tokens(sources) if t.category == "shadow"}
        assert ids_a == ids_b

    def test_shadow_ids_are_unique(self):
        tokens = [t for t in extract_tokens(_sources(js=REPEATED_SHADOW_JS)) if t.category == "shadow"]
        ids = [t.id for t in tokens]
        assert len(ids) == len(set(ids))


REPEATED_RADIUS_JS = """
borderRadius: '8px'
borderRadius: '8px'
borderRadius: '8px'
borderRadius: '4px'
borderRadius: '4px'
borderRadius: '4px'
borderRadius: '50%'
borderRadius: '50%'
borderRadius: '50%'
"""


class TestExtractRadii:
    def test_finds_frequently_used_radius(self):
        tokens = extract_tokens(_sources(js=REPEATED_RADIUS_JS))
        cats = {t.category for t in tokens}
        assert "radius" in cats

    def test_finds_pixel_radius_value(self):
        tokens = extract_tokens(_sources(js=REPEATED_RADIUS_JS))
        values = {t.value for t in tokens if t.category == "radius"}
        assert "8px" in values

    def test_finds_percentage_radius(self):
        tokens = extract_tokens(_sources(js=REPEATED_RADIUS_JS))
        values = {t.value for t in tokens if t.category == "radius"}
        assert "50%" in values

    def test_single_occurrence_radius_excluded(self):
        js = "borderRadius: '12px'"  # 1× only
        tokens = extract_tokens(_sources(js=js))
        assert not any(t.value == "12px" and t.category == "radius" for t in tokens)

    def test_radius_8px_gets_sm_label(self):
        tokens = extract_tokens(_sources(js=REPEATED_RADIUS_JS))
        t = next((t for t in tokens if t.value == "8px" and t.category == "radius"), None)
        assert t is not None
        assert t.label == "radius_sm"

    def test_radius_4px_gets_xs_label(self):
        tokens = extract_tokens(_sources(js=REPEATED_RADIUS_JS))
        t = next((t for t in tokens if t.value == "4px" and t.category == "radius"), None)
        assert t is not None
        assert t.label == "radius_xs"

    def test_radius_50pct_gets_full_label(self):
        tokens = extract_tokens(_sources(js=REPEATED_RADIUS_JS))
        t = next((t for t in tokens if t.value == "50%" and t.category == "radius"), None)
        assert t is not None
        assert t.label == "radius_full"

    def test_radius_from_css_detected(self):
        css = "border-radius: 4px; " * 3
        tokens = extract_tokens(_sources(css=css))
        assert any(t.category == "radius" for t in tokens)

    def test_radius_token_ids_are_deterministic(self):
        sources = _sources(js=REPEATED_RADIUS_JS)
        ids_a = {t.id for t in extract_tokens(sources) if t.category == "radius"}
        ids_b = {t.id for t in extract_tokens(sources) if t.category == "radius"}
        assert ids_a == ids_b


REPEATED_CSS_VARS_CSS = """
:root {
  --primary-color: #ffb81c;
  --background-dark: #1a1a1a;
  --spacing-base: 16px;
  --border-radius-sm: 4px;
  --font-size-body: 14px;
}
"""


class TestExtractCssVars:
    def test_finds_css_custom_properties(self):
        tokens = extract_tokens(_sources(css=REPEATED_CSS_VARS_CSS))
        cats = {t.category for t in tokens}
        assert "css_var" in cats

    def test_finds_primary_color_var(self):
        tokens = extract_tokens(_sources(css=REPEATED_CSS_VARS_CSS))
        labels = {t.label for t in tokens if t.category == "css_var"}
        assert "primary_color" in labels

    def test_finds_background_var(self):
        tokens = extract_tokens(_sources(css=REPEATED_CSS_VARS_CSS))
        labels = {t.label for t in tokens if t.category == "css_var"}
        assert "background_dark" in labels

    def test_var_value_preserved(self):
        tokens = extract_tokens(_sources(css=REPEATED_CSS_VARS_CSS))
        t = next((t for t in tokens if t.label == "primary_color"), None)
        assert t is not None
        assert "#ffb81c" in t.value

    def test_label_is_var_name_without_dashes(self):
        tokens = extract_tokens(_sources(css=REPEATED_CSS_VARS_CSS))
        for t in tokens:
            if t.category == "css_var":
                assert "--" not in t.label
                assert "-" not in t.label

    def test_css_vars_from_js_detected(self):
        js = "--brand-color: #ab1234; --brand-color: #ab1234;"
        tokens = extract_tokens(_sources(js=js))
        assert any(t.category == "css_var" for t in tokens)

    def test_css_var_ids_are_deterministic(self):
        sources = _sources(css=REPEATED_CSS_VARS_CSS)
        ids_a = {t.id for t in extract_tokens(sources) if t.category == "css_var"}
        ids_b = {t.id for t in extract_tokens(sources) if t.category == "css_var"}
        assert ids_a == ids_b

    def test_css_var_ids_are_unique(self):
        tokens = [t for t in extract_tokens(_sources(css=REPEATED_CSS_VARS_CSS))
                  if t.category == "css_var"]
        ids = [t.id for t in tokens]
        assert len(ids) == len(set(ids))


class TestBuildTokenMap:
    def test_maps_lowercase_value_to_token(self):
        token = DesignToken(id="c1", category="color",
                            label="primary", value="#ffb81c", usage=5)
        m = build_token_map([token])
        assert token in m.get("#ffb81c", [])

    def test_key_is_always_lowercase(self):
        token = DesignToken(id="c1", category="color",
                            label="x", value="#FFB81C", usage=2)
        m = build_token_map([token])
        assert "#ffb81c" in m

    def test_multiple_tokens_same_value_all_mapped(self):
        t1 = DesignToken(id="c1", category="color", label="a", value="#abc", usage=2)
        t2 = DesignToken(id="c2", category="color", label="b", value="#abc", usage=3)
        m = build_token_map([t1, t2])
        assert t1 in m["#abc"]
        assert t2 in m["#abc"]

    def test_empty_input_returns_empty_map(self):
        assert build_token_map([]) == {}
