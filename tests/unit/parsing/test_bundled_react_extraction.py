"""
Tests for bundled_react format extraction in source_loader.py.

The bundled_react format embeds base64/gzip-compressed JS, CSS, and HTML
inside <script> tags whose text is a JSON map:
  { "id1": { "data": "<base64>", "compressed": true, "mime": "text/javascript" }, ... }

These tests exercise _extract_bundled_react and _decompress_bundle_map without
touching the file system by constructing minimal HTML strings in-memory.
"""

from __future__ import annotations

import asyncio
import base64
import gzip
import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from design_graph.parsing.format_detector import BUNDLED_REACT
from design_graph.parsing.source_loader import (
    _decompress_bundle_map,
    _extract_bundled_react,
    load,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _b64gz(text: str) -> str:
    """Compress text with gzip and return base64 string."""
    return base64.b64encode(gzip.compress(text.encode())).decode()


def _b64(text: str) -> str:
    """Return base64-encoded text (uncompressed)."""
    return base64.b64encode(text.encode()).decode()


def _bundle_html(entries: dict) -> str:
    """
    Build a minimal bundled_react HTML document.
    entries: { "id": {"data": "<b64>", "compressed": bool, "mime": str} }
    """
    bundle_json = json.dumps(entries)
    # Pad to ensure len > 10_000 so _extract_bundled_react treats it as a bundle map
    padding = "// " + "x" * max(0, 10_100 - len(bundle_json))
    padded  = bundle_json[:-1] + f', "_pad": {json.dumps(padding)}' + "}"
    return f"<!DOCTYPE html><html><body><script>{padded}</script></body></html>"


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


# ── _decompress_bundle_map ────────────────────────────────────────────────────

class TestDecompressBundleMap:
    def test_extracts_compressed_js(self):
        js_code = "function BtnPrimary() { return <button>OK</button>; }"
        bundle = json.dumps({
            "js1": {"data": _b64gz(js_code), "compressed": True, "mime": "text/javascript"}
        })
        js_parts, css_parts, html_part = _decompress_bundle_map(bundle)
        assert any(js_code in p for p in js_parts)
        assert html_part == ""
        assert css_parts == []

    def test_extracts_uncompressed_js(self):
        js_code = "function SectionCard() { return <div/>; }"
        bundle = json.dumps({
            "js1": {"data": _b64(js_code), "compressed": False, "mime": "text/javascript"}
        })
        js_parts, _, _ = _decompress_bundle_map(bundle)
        assert any(js_code in p for p in js_parts)

    def test_extracts_css_by_mime_type(self):
        css_code = ".btn { color: #ffb81c; }"
        bundle = json.dumps({
            "css1": {"data": _b64(css_code), "compressed": False, "mime": "text/css"}
        })
        _, css_parts, _ = _decompress_bundle_map(bundle)
        assert any(css_code in p for p in css_parts)

    def test_extracts_inner_html_by_doctype(self):
        html_content = "<!DOCTYPE html><html><body>App</body></html>"
        bundle = json.dumps({
            "html1": {"data": _b64(html_content), "compressed": False, "mime": "text/html"}
        })
        _, _, html_part = _decompress_bundle_map(bundle)
        assert "<!DOCTYPE" in html_part

    def test_compressed_html_extracted(self):
        html_content = "<!DOCTYPE html><html><body>Compressed</body></html>"
        bundle = json.dumps({
            "html1": {"data": _b64gz(html_content), "compressed": True, "mime": "text/html"}
        })
        _, _, html_part = _decompress_bundle_map(bundle)
        assert "Compressed" in html_part

    def test_multiple_entries_all_extracted(self):
        js1 = "function Comp1() {}"
        js2 = "function Comp2() {}"
        bundle = json.dumps({
            "a": {"data": _b64(js1), "compressed": False, "mime": "application/javascript"},
            "b": {"data": _b64(js2), "compressed": False, "mime": "application/javascript"},
        })
        js_parts, _, _ = _decompress_bundle_map(bundle)
        combined = "\n".join(js_parts)
        assert "Comp1" in combined
        assert "Comp2" in combined

    def test_malformed_json_returns_empty(self):
        js_parts, css_parts, html_part = _decompress_bundle_map("{broken json{{")
        assert js_parts == []
        assert css_parts == []
        assert html_part == ""

    def test_empty_data_field_skipped(self):
        bundle = json.dumps({"id": {"data": "", "compressed": False, "mime": "text/javascript"}})
        js_parts, _, _ = _decompress_bundle_map(bundle)
        assert js_parts == []

    def test_missing_data_field_skipped(self):
        bundle = json.dumps({"id": {"compressed": False, "mime": "text/javascript"}})
        js_parts, _, _ = _decompress_bundle_map(bundle)
        assert js_parts == []

    def test_corrupt_base64_skipped_gracefully(self):
        bundle = json.dumps({
            "id": {"data": "not!!valid__base64$$", "compressed": False, "mime": "text/javascript"}
        })
        js_parts, _, _ = _decompress_bundle_map(bundle)
        assert js_parts == []

    def test_corrupt_gzip_skipped_gracefully(self):
        not_gzip = base64.b64encode(b"this is not gzip data").decode()
        bundle = json.dumps({
            "id": {"data": not_gzip, "compressed": True, "mime": "text/javascript"}
        })
        js_parts, _, _ = _decompress_bundle_map(bundle)
        assert js_parts == []

    def test_bundle_is_a_plain_html_string(self):
        html_str = json.dumps("<!DOCTYPE html><html><body>Direct</body></html>")
        js_parts, css_parts, html_part = _decompress_bundle_map(html_str)
        assert "Direct" in html_part
        assert js_parts == []

    def test_non_dict_bundle_returns_empty(self):
        js_parts, css_parts, html_part = _decompress_bundle_map("[1, 2, 3]")
        assert js_parts == []


# ── _extract_bundled_react ────────────────────────────────────────────────────

class TestExtractBundledReact:
    def test_returns_js_from_compressed_bundle(self):
        js_code = "function BtnPrimary(props) { return <button>OK</button>; }"
        html = _bundle_html({
            "js": {"data": _b64gz(js_code), "compressed": True, "mime": "text/javascript"}
        })
        js, css, inner = _extract_bundled_react(_soup(html))
        assert "BtnPrimary" in js

    def test_returns_css_from_bundle(self):
        css_code = ".btn { color: #ffb81c; background: #1f1f1f; }"
        html = _bundle_html({
            "css": {"data": _b64(css_code), "compressed": False, "mime": "text/css"}
        })
        js, css_out, _ = _extract_bundled_react(_soup(html))
        assert css_code in css_out

    def test_extracts_inner_html_from_bundle(self):
        inner = "<!DOCTYPE html><html><body><div id='app'>App</div></body></html>"
        html  = _bundle_html({
            "html": {"data": _b64(inner), "compressed": False, "mime": "text/html"}
        })
        _, _, extracted_html = _extract_bundled_react(_soup(html))
        assert "App" in extracted_html

    def test_fallback_inner_html_when_no_html_entry(self):
        js_code = "function Comp() {}"
        html = _bundle_html({
            "js": {"data": _b64(js_code), "compressed": False, "mime": "text/javascript"}
        })
        _, _, inner = _extract_bundled_react(_soup(html))
        assert inner  # fallback uses full soup string

    def test_short_json_string_treated_as_inner_html(self):
        inner_html_str = "<!DOCTYPE html><html><body>Inline</body></html>"
        escaped = json.dumps(inner_html_str)
        html = f"<html><body><script>{escaped}</script></body></html>"
        _, _, inner = _extract_bundled_react(_soup(html))
        assert "Inline" in inner

    def test_plain_js_block_included_in_output(self):
        long_js = "function Foo() {}" + " // comment" * 100  # ensure > 1000 chars
        html = f"<html><body><script>{long_js}</script></body></html>"
        js, _, _ = _extract_bundled_react(_soup(html))
        assert "Foo" in js

    def test_empty_scripts_ignored(self):
        html = "<html><body><script>  </script></body></html>"
        js, css, _ = _extract_bundled_react(_soup(html))
        assert js == ""
        assert css == ""

    def test_returns_three_strings(self):
        html = "<html><body></body></html>"
        result = _extract_bundled_react(_soup(html))
        assert len(result) == 3
        assert all(isinstance(x, str) for x in result)


# ── load() with bundled_react format fixture ─────────────────────────────────

class TestLoadBundledReactFormat:
    """Integration-level: build a minimal bundled_react HTML file and load it."""

    @pytest.fixture
    def bundled_html_file(self, tmp_path):
        js_code = (
            "function BtnPrimary(props) {\n"
            "  return <button style={{backgroundColor:'#ffb81c'}}>OK</button>;\n"
            "}\n"
            "function RestaurantsPage() {\n"
            "  return <div><BtnPrimary /></div>;\n"
            "}\n"
        )
        css_code = ".btn { color: #ffb81c; padding: 8px; margin: 8px; }"
        inner_doc = "<!DOCTYPE html><html><body><div id='root'></div></body></html>"

        entries = {
            "js1":  {"data": _b64gz(js_code),   "compressed": True,  "mime": "text/javascript"},
            "css1": {"data": _b64(css_code),     "compressed": False, "mime": "text/css"},
            "html": {"data": _b64(inner_doc),    "compressed": False, "mime": "text/html"},
        }
        bundle_json = json.dumps(entries)
        # Force bundled_react detection: > 50000 chars + "compressed: true"
        padding = "// " + "x" * max(0, 51_000 - len(bundle_json))
        padded  = bundle_json[:-1] + f', "_pad": {json.dumps(padding)}' + "}"

        html_path = tmp_path / "bundle.html"
        html_path.write_text(
            f"<!DOCTYPE html><html><body><script>{padded}</script></body></html>",
            encoding="utf-8",
        )
        return html_path

    def test_format_detected_as_bundled_react(self, bundled_html_file):
        sources = asyncio.run(load(bundled_html_file))
        assert sources.format == BUNDLED_REACT

    def test_js_contains_component_functions(self, bundled_html_file):
        sources = asyncio.run(load(bundled_html_file))
        assert "BtnPrimary" in sources.js
        assert "RestaurantsPage" in sources.js

    def test_css_contains_styles(self, bundled_html_file):
        sources = asyncio.run(load(bundled_html_file))
        assert "#ffb81c" in sources.css

    def test_inner_html_contains_doctype(self, bundled_html_file):
        sources = asyncio.run(load(bundled_html_file))
        assert "<!DOCTYPE" in sources.inner_html or "root" in sources.inner_html

    def test_html_hash_is_deterministic(self, bundled_html_file):
        a = asyncio.run(load(bundled_html_file))
        b = asyncio.run(load(bundled_html_file))
        assert a.html_hash == b.html_hash

    def test_raw_sources_fields_are_strings(self, bundled_html_file):
        sources = asyncio.run(load(bundled_html_file))
        assert isinstance(sources.js, str)
        assert isinstance(sources.css, str)
        assert isinstance(sources.inner_html, str)
