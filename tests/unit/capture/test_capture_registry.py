"""Capture contract: reading a prototype once and routing it to the capture that understands it."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

from design_graph.capture.base import CaptureResult, PrototypeDocument, UnsupportedPrototypeError
from design_graph.capture.registry import capture_for

FIXTURE_DIR = Path(__file__).parent.parent.parent / "fixtures"


class TestPrototypeDocument:
    def test_digest_is_md5_of_raw_bytes(self):
        path = FIXTURE_DIR / "simple.html"
        document = PrototypeDocument.read(path)
        assert document.digest == hashlib.md5(path.read_bytes()).hexdigest()

    def test_text_is_decoded_content(self):
        path = FIXTURE_DIR / "simple.html"
        assert PrototypeDocument.read(path).text == path.read_text(encoding="utf-8")

    def test_invalid_utf8_is_replaced_not_raised(self, tmp_path):
        path = tmp_path / "latin1.html"
        path.write_bytes(b"<html><body>caf\xe9</body></html>")
        assert "caf�" in PrototypeDocument.read(path).text

    def test_missing_file_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            PrototypeDocument.read(tmp_path / "absent.html")

    def test_directory_is_rejected(self, tmp_path):
        with pytest.raises(UnsupportedPrototypeError):
            PrototypeDocument.read(tmp_path)

    def test_file_above_size_limit_is_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr("design_graph.capture.base.MAX_PROTOTYPE_BYTES", 10)
        path = tmp_path / "big.html"
        path.write_text("<html>" + "x" * 20 + "</html>")
        with pytest.raises(UnsupportedPrototypeError, match="too large"):
            PrototypeDocument.read(path)


class TestCaptureSelection:
    def test_react_prototype_is_captured_as_html_prototype(self):
        document = PrototypeDocument.read(FIXTURE_DIR / "simple.html")
        assert capture_for(document).name == "html_prototype"

    def test_plain_html_is_captured_as_html_prototype(self):
        document = PrototypeDocument.read(FIXTURE_DIR / "plain.html")
        assert capture_for(document).name == "html_prototype"

    def test_document_without_html_markup_is_unsupported(self, tmp_path):
        path = tmp_path / "notes.html"
        path.write_text("just some notes, no markup at all")
        with pytest.raises(UnsupportedPrototypeError, match="notes.html"):
            capture_for(PrototypeDocument.read(path))

    def test_binary_file_is_unsupported(self, tmp_path):
        path = tmp_path / "image.html"
        path.write_bytes(bytes(range(256)) * 4)
        with pytest.raises(UnsupportedPrototypeError):
            capture_for(PrototypeDocument.read(path))


class TestHtmlPrototypeCapture:
    def _capture(self, fixture: str) -> CaptureResult:
        document = PrototypeDocument.read(FIXTURE_DIR / fixture)
        return asyncio.run(capture_for(document).capture(document, concurrency=2))

    def test_react_prototype_yields_screens_and_components(self):
        result = self._capture("simple.html")
        assert result.capture == "html_prototype"
        assert result.screens
        assert {c.name for c in result.components} >= {"BtnPrimary"}

    def test_plain_html_yields_single_synthetic_screen(self):
        result = self._capture("plain.html")
        assert len(result.screens) == 1
        assert result.components
        assert result.module_texts == []

    def test_sections_are_keyed_by_screen_name(self):
        result = self._capture("simple.html")
        assert set(result.sections) <= {screen.name for screen in result.screens}

    def test_skipped_entries_defaults_to_zero_for_unbundled_html(self):
        assert self._capture("simple.html").skipped_entries == 0


class TestCaptureByName:
    def test_capture_is_found_by_its_name(self):
        from design_graph.capture.registry import capture_named
        assert capture_named("html_prototype").name == "html_prototype"

    def test_unknown_capture_name_is_unsupported(self):
        from design_graph.capture.registry import capture_named
        with pytest.raises(UnsupportedPrototypeError, match="no_such_capture"):
            capture_named("no_such_capture")


class TestHtmlPrototypeFragment:
    """An agent-written fragment is read the same way the capture reads a whole prototype."""

    def _fragment(self, source):
        from design_graph.capture.registry import capture_named
        return capture_named("html_prototype").capture_fragment(source)

    def test_fragment_yields_its_inline_styles_children_and_texts(self):
        comp = self._fragment('<button style={{color: "red"}}><Icon />Save draft</button>')
        assert ("color", "red") in {(s.property, s.value) for s in comp.styles}
        assert "Icon" in comp.child_refs
        assert "Save draft" in {t.content for t in comp.texts}

    @pytest.mark.parametrize("source", ["", "   \n  "])
    def test_blank_fragment_yields_nothing(self, source):
        assert self._fragment(source) is None

    def test_spread_style_reference_stays_unresolved_without_the_rest_of_the_file(self):
        # A spread of a shared style object can't resolve in an isolated
        # fragment — its own properties are absent, never wrong.
        comp = self._fragment('<div style={{...sharedStyle, width: 34}} />')
        assert "width" in {s.property for s in comp.styles}
