"""The bundle container: strict decoding with a bounded expansion."""

from __future__ import annotations

import base64
import gzip
import json

import pytest

from design_graph.capture import bundler
from design_graph.capture.bundler import BundleEntryError, decode_entry, read_bundle


def _entry(content: bytes, compressed: bool = True) -> dict:
    data = gzip.compress(content) if compressed else content
    return {"mime": "text/plain", "compressed": compressed, "data": base64.b64encode(data).decode()}


def _document(manifest: dict, template: str = "<html></html>", order: list | None = None) -> str:
    return (
        f'<script type="__bundler/manifest">{json.dumps(manifest)}</script>'
        f'<script type="__bundler/page_order">{json.dumps(order or [])}</script>'
        f'<script type="__bundler/template">{json.dumps(template)}</script>'
    )


class TestReadBundle:
    def test_reads_manifest_template_and_order(self):
        bundle = read_bundle(_document({"a": _entry(b"x")}, "<p>t</p>", ["a"]))
        assert bundle.template == "<p>t</p>" and bundle.page_order == ["a"]
        assert bundle.entry("a") == b"x"

    def test_document_without_bundle_scripts_is_not_a_bundle(self):
        assert read_bundle("<html><body>plain</body></html>") is None

    def test_malformed_manifest_is_not_a_bundle(self):
        text = '<script type="__bundler/manifest">{broken</script><script type="__bundler/template">"x"</script>'
        assert read_bundle(text) is None

    def test_missing_entry_is_an_entry_error(self):
        with pytest.raises(BundleEntryError):
            read_bundle(_document({})).entry("ghost")


class TestDecodeEntry:
    def test_uncompressed_entry_is_plain_base64(self):
        assert decode_entry(_entry(b"hello", compressed=False)) == b"hello"

    def test_invalid_base64_is_rejected_not_silently_skipped(self):
        entry = _entry(b"hello")
        entry["data"] = "!!" + entry["data"]
        with pytest.raises(BundleEntryError, match="base64"):
            decode_entry(entry)

    def test_invalid_gzip_is_rejected(self):
        entry = {"compressed": True, "data": base64.b64encode(b"not gzip").decode()}
        with pytest.raises(BundleEntryError, match="gzip"):
            decode_entry(entry)

    def test_entry_expanding_beyond_the_limit_is_rejected(self, monkeypatch):
        monkeypatch.setattr(bundler, "MAX_ENTRY_BYTES", 1024)
        with pytest.raises(BundleEntryError, match="expands beyond"):
            decode_entry(_entry(b"0" * 100_000))
