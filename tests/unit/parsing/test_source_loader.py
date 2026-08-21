"""Tests for source_loader — T01."""

import asyncio
import base64
import hashlib
import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from design_graph.core.models import RawSources
from design_graph.parsing.source_loader import _extract_bundled_react, load

FIXTURE_DIR = Path(__file__).parent.parent.parent / "fixtures"
SIMPLE_HTML = FIXTURE_DIR / "simple.html"


class TestLoad:
    def test_returns_raw_sources_instance(self):
        sources = asyncio.run(load(SIMPLE_HTML))
        assert isinstance(sources, RawSources)

    def test_js_is_non_empty_string(self):
        sources = asyncio.run(load(SIMPLE_HTML))
        assert isinstance(sources.js, str)
        assert len(sources.js) > 0

    def test_css_is_string(self):
        sources = asyncio.run(load(SIMPLE_HTML))
        assert isinstance(sources.css, str)

    def test_inner_html_is_string(self):
        sources = asyncio.run(load(SIMPLE_HTML))
        assert isinstance(sources.inner_html, str)

    def test_html_hash_is_md5_hex(self):
        sources = asyncio.run(load(SIMPLE_HTML))
        assert len(sources.html_hash) == 32
        int(sources.html_hash, 16)  # must be valid hex

    def test_html_hash_is_deterministic(self):
        a = asyncio.run(load(SIMPLE_HTML))
        b = asyncio.run(load(SIMPLE_HTML))
        assert a.html_hash == b.html_hash

    def test_html_hash_matches_file_content(self):
        raw = SIMPLE_HTML.read_bytes()
        expected = hashlib.md5(raw).hexdigest()
        sources = asyncio.run(load(SIMPLE_HTML))
        assert sources.html_hash == expected

    def test_format_field_is_valid(self):
        sources = asyncio.run(load(SIMPLE_HTML))
        assert sources.format in {"bundled_react", "tailwind", "plain_html"}

    def test_different_files_have_different_hashes(self, tmp_path):
        f1 = tmp_path / "a.html"
        f2 = tmp_path / "b.html"
        f1.write_text("<html>version one</html>")
        f2.write_text("<html>version two</html>")
        h1 = asyncio.run(load(f1)).html_hash
        h2 = asyncio.run(load(f2)).html_hash
        assert h1 != h2

    def test_raw_sources_is_frozen(self):
        sources = asyncio.run(load(SIMPLE_HTML))
        with pytest.raises((AttributeError, TypeError)):
            sources.js = "mutated"  # type: ignore[misc]

    def test_malformed_bundle_json_does_not_raise(self, tmp_path):
        bad = tmp_path / "bad.html"
        bad.write_text('<html><script>{"broken": json_not_valid}</script></html>')
        sources = asyncio.run(load(bad))
        assert isinstance(sources.js, str)  # graceful fallback

    def test_missing_file_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            asyncio.run(load(tmp_path / "nonexistent.html"))

    def test_plain_html_script_tags_extracted(self, tmp_path):
        f = tmp_path / "plain.html"
        f.write_text(
            "<html><script>function MyComp() { return 1; }</script></html>"
        )
        sources = asyncio.run(load(f))
        assert "MyComp" in sources.js


def _bundle_soup(inner_html: str) -> BeautifulSoup:
    """
    A minimal bundled_react <script> whose JSON bundle map decodes to
    `inner_html` for the html entry. Padded past _extract_bundled_react's
    10_000-char "is this the actual bundle" threshold with a throwaway JS
    entry — real bundles are always this large; a tiny JSON test fixture
    isn't, so it must be padded to be recognised at all.
    """
    bundle = {
        "index.html": {
            "data": base64.b64encode(inner_html.encode()).decode(),
            "compressed": False,
            "mime": "text/html",
        },
        "padding.js": {
            "data": base64.b64encode(b"//" + b"x" * 10_000).decode(),
            "compressed": False,
            "mime": "application/javascript",
        },
    }
    html = f"<html><body><script>{json.dumps(bundle)}</script></body></html>"
    return BeautifulSoup(html, "html.parser")


class TestExtractBundledReactStyleTagInInnerHtml:
    """
    C24/T44 — real evidence: source_loader.load() against the checked-in
    `iPede Manager v15.1.html` returns sources.css == "" even though
    sources.inner_html (4692 bytes) contains a real <style> tag with rules
    including `input:focus, select:focus, textarea:focus {...}` and
    `.pulse-dot {...}` — _extract_bundled_react only harvested CSS from
    bundle entries whose mime contains "css", never from a <style> tag
    already sitting inside the inner_html it resolves itself.
    """

    STYLE_INNER_HTML = (
        "<!DOCTYPE html><html><head><style>"
        ".pulse-dot { animation: pulseDot 1.8s ease-in-out infinite; }\n"
        "input:focus, select:focus, textarea:focus { outline: none; "
        "border-color: #FFB81C !important; }"
        "</style></head><body></body></html>"
    )

    def test_style_tag_css_is_captured(self):
        _js, css, _html, _skipped = _extract_bundled_react(_bundle_soup(self.STYLE_INNER_HTML))
        assert ".pulse-dot" in css
        assert "input:focus" in css

    def test_inner_html_itself_is_still_returned_unchanged(self):
        _js, _css, html_out, _skipped = _extract_bundled_react(_bundle_soup(self.STYLE_INNER_HTML))
        assert html_out == self.STYLE_INNER_HTML

    def test_no_style_tag_yields_empty_css_without_error(self):
        inner_html = "<!DOCTYPE html><html><body><div>no styles here</div></body></html>"
        _js, css, _html, _skipped = _extract_bundled_react(_bundle_soup(inner_html))
        assert css == ""

    def test_style_from_bundle_css_mime_entry_still_works_alongside_inner_html_style(self):
        # Regression: a bundle that already has a separate CSS-mime entry
        # must keep contributing — the new source is additive, not a
        # replacement.
        bundle = {
            "index.html": {
                "data": base64.b64encode(self.STYLE_INNER_HTML.encode()).decode(),
                "compressed": False,
                "mime": "text/html",
            },
            "styles.css": {
                "data": base64.b64encode(b".from-bundle-entry { color: red; }" + b"/*" + b"x" * 10_000 + b"*/").decode(),
                "compressed": False,
                "mime": "text/css",
            },
        }
        html = f"<html><body><script>{json.dumps(bundle)}</script></body></html>"
        soup = BeautifulSoup(html, "html.parser")
        _js, css, _html, _skipped = _extract_bundled_react(soup)
        assert ".from-bundle-entry" in css
        assert ".pulse-dot" in css
