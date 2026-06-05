"""Tests for source_loader — T01."""

import asyncio
import hashlib
from pathlib import Path

import pytest

from design_graph.core.models import RawSources
from design_graph.parsing.source_loader import load

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
