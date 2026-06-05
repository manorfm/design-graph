"""Tests for format_detector — T02."""

import pytest
from bs4 import BeautifulSoup

from design_graph.parsing.format_detector import (
    BUNDLED_REACT,
    PLAIN_HTML,
    TAILWIND,
    detect,
)


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


class TestDetectBundledReact:
    def test_detects_compressed_bundle_flag(self):
        html = '<script>{"compressed": true, "data": "abc"}</script>'
        assert detect(html, _soup(html)) == BUNDLED_REACT

    def test_detects_large_script_with_create_element(self):
        big_js = "createElement" + "x" * 100_001
        html = f"<script>{big_js}</script>"
        assert detect(html, _soup(html)) == BUNDLED_REACT

    def test_does_not_flag_small_script_with_create_element(self):
        small_js = "createElement x"
        html = f"<script>{small_js}</script>"
        result = detect(html, _soup(html))
        assert result != BUNDLED_REACT


class TestDetectTailwind:
    def test_detects_flex_utility_class(self):
        html = "<style>.flex { display: flex }</style>"
        assert detect(html, _soup(html)) == TAILWIND

    def test_detects_padding_utility_class(self):
        html = "<style>.p-4 { padding: 1rem }</style>"
        assert detect(html, _soup(html)) == TAILWIND

    def test_detects_bg_utility_class(self):
        html = "<style>.bg-red { background: red }</style>"
        assert detect(html, _soup(html)) == TAILWIND

    def test_does_not_flag_regular_css(self):
        html = "<style>.my-class { color: red }</style>"
        result = detect(html, _soup(html))
        assert result != TAILWIND


class TestDetectPlainHtml:
    def test_plain_html_is_default(self):
        html = "<html><body><p>Hello</p></body></html>"
        assert detect(html, _soup(html)) == PLAIN_HTML

    def test_empty_html_returns_plain(self):
        assert detect("", _soup("")) == PLAIN_HTML

    def test_unknown_content_returns_plain(self):
        html = "<div class='custom-widget'>content</div>"
        assert detect(html, _soup(html)) == PLAIN_HTML


class TestDetectReturnValues:
    VALID_FORMATS = {BUNDLED_REACT, TAILWIND, PLAIN_HTML}

    @pytest.mark.parametrize("html", [
        "",
        "<div/>",
        "<script>not json</script>",
        f"<script>{'x' * 200_000}</script>",
        '<script>{"compressed": true}</script>',
    ])
    def test_always_returns_valid_format(self, html):
        result = detect(html, _soup(html))
        assert result in self.VALID_FORMATS

    def test_never_raises_on_malformed_html(self):
        malformed = "<<script>>>broken{{json"
        result = detect(malformed, _soup(malformed))
        assert result in self.VALID_FORMATS
