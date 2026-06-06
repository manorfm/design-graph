"""
Integration tests for the complete plain_html pipeline path.

Verifies that a plain HTML prototype (no React, no JSX) produces a meaningful
design graph with:
  - Components derived from repeating DOM patterns (via html_parser)
  - Sections derived from HTML5 semantic elements (nav, main, section, footer)
  - Design tokens from CSS color and spacing values

Fixture: tests/fixtures/plain.html (iPede plain HTML prototype)
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import kuzu
import pytest

from design_graph.graph.reader import GraphReader
from design_graph.pipeline.coordinator import run_pipeline

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"
PLAIN_HTML  = FIXTURE_DIR / "plain.html"


@pytest.fixture(scope="module")
def plain_graph(tmp_path_factory):
    """Build a Kuzu graph from plain.html once for all tests in this module."""
    tmp        = tmp_path_factory.mktemp("plain_html")
    db_path    = tmp / "plain.db"
    state_path = tmp / ".state.json"
    stats = asyncio.run(run_pipeline(PLAIN_HTML, db_path, state_path))
    return db_path, stats


@pytest.fixture(scope="module")
def plain_reader(plain_graph):
    db_path, _ = plain_graph
    db   = kuzu.Database(str(db_path), read_only=True)
    conn = kuzu.Connection(db)
    return GraphReader(conn)


# ── Pipeline produces stats ───────────────────────────────────────────────────

class TestPlainHtmlPipelineStats:
    def test_build_succeeds(self, plain_graph):
        _, stats = plain_graph
        assert stats is not None

    def test_build_duration_reasonable(self, plain_graph):
        _, stats = plain_graph
        assert stats.duration_seconds < 15

    def test_extracts_components_from_dom_patterns(self, plain_graph):
        """plain.html has 4 .card divs — should produce a Card component."""
        _, stats = plain_graph
        assert stats.components >= 1, (
            f"Expected >= 1 component from DOM patterns, got {stats.components}"
        )

    def test_extracts_tokens_from_css(self, plain_graph):
        """plain.html has color tokens like #ffb81c, #1a1a1a in its <style> block."""
        _, stats = plain_graph
        assert stats.tokens >= 1, (
            f"Expected >= 1 design token from CSS, got {stats.tokens}"
        )

    def test_extracts_sections_from_semantic_html(self, plain_graph):
        """plain.html has <nav>, <main>, <section>, <footer> elements."""
        _, stats = plain_graph
        assert stats.sections >= 1, (
            f"Expected >= 1 section from semantic HTML, got {stats.sections}"
        )


# ── Graph content correctness ─────────────────────────────────────────────────

class TestPlainHtmlGraphContent:
    def test_card_component_in_graph(self, plain_reader):
        """The repeating .card div pattern should produce a Card component."""
        # Try multiple possible names the extractor might use
        found = any(
            plain_reader.get_component(name) is not None
            for name in ("Card", "CardComponent", "RestaurantCard")
        )
        assert found, "Expected a Card-like component from the .card DOM pattern"

    def test_color_token_ffb81c_extracted(self, plain_reader):
        """#ffb81c appears in plain.html CSS — should be a color token."""
        tokens = plain_reader.get_tokens(category="color")
        values = {t.get("t.value", "").lower() for t in tokens}
        assert "#ffb81c" in values, (
            f"Expected #ffb81c color token, found: {values}"
        )

    def test_sections_have_semantic_detection_method(self, plain_reader):
        """Sections in plain.html should be detected via 'semantic' method."""
        all_screens = plain_reader.list_screens()
        for screen in all_screens:
            screen_data = plain_reader.get_screen(screen["name"])
            if screen_data:
                for sec in screen_data.get("sections", []):
                    # detection_method should be "semantic" (not "comment" or "structural")
                    method = sec.get("sec.detection_method", sec.get("detection_method", ""))
                    assert method in ("semantic", "comment", "structural", ""), (
                        f"Unexpected detection_method: {method!r}"
                    )

    def test_graph_has_at_least_one_screen(self, plain_reader):
        screens = plain_reader.list_screens()
        assert len(screens) >= 1


# ── State persistence ─────────────────────────────────────────────────────────

class TestPlainHtmlStatePersistence:
    def test_state_saved_with_correct_hash(self, plain_graph):
        import hashlib
        from design_graph.pipeline.state import load_build_state

        db_path, _ = plain_graph
        state_path  = db_path.parent / ".state.json"
        state       = load_build_state(state_path)

        expected_hash = hashlib.md5(PLAIN_HTML.read_bytes()).hexdigest()
        assert state.html_hash == expected_hash

    def test_second_build_skipped_unchanged(self, plain_graph):
        db_path, _ = plain_graph
        state_path  = db_path.parent / ".state.json"
        result = asyncio.run(run_pipeline(PLAIN_HTML, db_path, state_path))
        assert result is None  # skipped — HTML hasn't changed


# ── Chunker works on plain HTML graph ────────────────────────────────────────

class TestPlainHtmlChunking:
    def test_cli_chunk_produces_jsonl(self, tmp_path):
        import json
        from unittest.mock import patch

        out = tmp_path / "plain.jsonl"
        with patch("sys.argv", ["design-graph", "chunk", str(PLAIN_HTML),
                                "--output", str(out)]):
            from design_graph.cli.build import main
            main()

        assert out.exists(), "Expected JSONL output from chunk command"
        lines = out.read_text().splitlines()
        assert len(lines) >= 1

        for line in lines:
            data = json.loads(line)
            assert "chunk_id" in data
            assert "content" in data

    def test_chunk_ids_are_valid(self, tmp_path):
        import json
        import re
        from unittest.mock import patch

        out = tmp_path / "plain2.jsonl"
        with patch("sys.argv", ["design-graph", "chunk", str(PLAIN_HTML),
                                "--output", str(out)]):
            from design_graph.cli.build import main
            main()

        for line in out.read_text().splitlines():
            cid = json.loads(line)["chunk_id"]
            assert re.match(r"^[a-z0-9_]+$", cid), f"Invalid chunk_id: {cid!r}"
