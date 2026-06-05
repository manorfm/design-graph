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
    def test_all_tokens_have_required_fields(self):
        tokens = extract_tokens(_sources(js=REPEATED_COLOR_JS + REPEATED_SPACING_JS))
        for t in tokens:
            assert t.id, "id must be non-empty"
            assert t.category in {"color", "spacing"}, f"unexpected category: {t.category}"
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
