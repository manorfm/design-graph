"""
Tests for chunker.py edge cases not covered by test_chunker.py.

Targets:
  - _unique_chunk_id collision counter (lines 159-160)
  - _build_screen_content max_chars truncation (line 180)
  - _section_fallback_content when jsx_snippet is empty (lines 194-195)
  - _split_section_by_components: component without JSX (line 214)
"""

from __future__ import annotations

import pytest

from design_graph.core.models import (
    ExtractedComponent,
    ExtractedScreen,
    ExtractedSection,
)
from design_graph.extraction.chunker import (
    _build_screen_content,
    _section_fallback_content,
    _unique_chunk_id,
    chunk_extracted_data,
)


# ── _unique_chunk_id collision handling ──────────────────────────────────────

class TestUniqueChunkIdCollisions:
    def test_no_collision_returns_base_slug(self):
        used: set[str] = set()
        cid = _unique_chunk_id("MyScreen", used)
        assert cid == "my_screen"

    def test_first_collision_appends_1(self):
        used: set[str] = {"my_screen"}
        cid = _unique_chunk_id("MyScreen", used)
        assert cid == "my_screen_1"

    def test_second_collision_appends_2(self):
        used: set[str] = {"my_screen", "my_screen_1"}
        cid = _unique_chunk_id("MyScreen", used)
        assert cid == "my_screen_2"

    def test_id_added_to_used_set(self):
        used: set[str] = set()
        _unique_chunk_id("Page", used)
        assert "page" in used

    def test_multiple_calls_all_unique(self):
        used: set[str] = set()
        ids = [_unique_chunk_id("SameName", used) for _ in range(5)]
        assert len(ids) == len(set(ids))


# ── _build_screen_content max_chars truncation ────────────────────────────────

class TestBuildScreenContentMaxChars:
    def test_stops_when_total_exceeds_max_chars(self):
        screen = ExtractedScreen(
            name="BigScreen",
            component_refs=["CompA", "CompB", "CompC"],
            sections_count=0,
        )
        # Each component has 600 chars of JSX; with max_chars=1000, only 1 should fit
        big_jsx = "x" * 600
        components = {
            "CompA": ExtractedComponent("CompA", "card", big_jsx, 1, "", [], [], [], []),
            "CompB": ExtractedComponent("CompB", "card", big_jsx, 1, "", [], [], [], []),
            "CompC": ExtractedComponent("CompC", "card", big_jsx, 1, "", [], [], [], []),
        }
        content = _build_screen_content(screen, components, max_chars=1_000)
        assert "CompA" in content
        assert "CompB" not in content  # would exceed max_chars

    def test_fallback_when_no_component_has_jsx(self):
        screen = ExtractedScreen(
            name="EmptyScreen",
            component_refs=["CompX"],
            sections_count=0,
        )
        comps = {
            "CompX": ExtractedComponent("CompX", "card", "", 1, "", [], [], [], [])
        }
        content = _build_screen_content(screen, comps, max_chars=12_000)
        assert "EmptyScreen" in content or "CompX" in content

    def test_fallback_when_no_components_dict(self):
        screen = ExtractedScreen(
            name="NoComps", component_refs=["Ghost"], sections_count=0
        )
        content = _build_screen_content(screen, {}, max_chars=12_000)
        assert "NoComps" in content or "Ghost" in content


# ── _section_fallback_content ─────────────────────────────────────────────────

class TestSectionFallbackContent:
    def _section(self, name: str, refs: list[str], jsx: str = "") -> ExtractedSection:
        return ExtractedSection(
            id=f"sec_{name.lower()}", screen="TestPage", name=name,
            styles={}, component_refs=refs, texts=[],
            jsx_snippet=jsx, detection_method="comment",
        )

    def test_returns_string_with_section_name(self):
        sec = self._section("Header", ["BtnPrimary"])
        content = _section_fallback_content(sec)
        assert "Header" in content

    def test_includes_component_refs(self):
        sec = self._section("Footer", ["BtnPrimary", "NavLink"])
        content = _section_fallback_content(sec)
        assert "BtnPrimary" in content

    def test_no_refs_shows_none(self):
        sec = self._section("Empty", [])
        content = _section_fallback_content(sec)
        assert "none" in content.lower() or "Empty" in content

    def test_chunk_data_uses_fallback_when_section_has_no_jsx(self):
        screen = ExtractedScreen("TestPage", ["BtnPrimary"], sections_count=1)
        section = self._section("Header", ["BtnPrimary"], jsx="")  # empty jsx
        chunks = chunk_extracted_data(
            [screen],
            {"TestPage": [section]},
            {},
        )
        sec_chunks = [c for c in chunks if c.level == "section"]
        assert len(sec_chunks) >= 1
        # Content must not be empty even with no JSX
        for c in sec_chunks:
            assert c.content.strip() != ""


# ── _split_section_by_components: no JSX fallback ────────────────────────────

class TestSplitSectionByComponentsNoJsx:
    def test_component_without_jsx_uses_comment_fallback(self):
        screen  = ExtractedScreen("TestPage", ["GhostComp"], sections_count=1)
        section = ExtractedSection(
            id="sec_big", screen="TestPage", name="Big",
            styles={}, component_refs=["GhostComp"], texts=[],
            jsx_snippet="X" * 15_000,  # force per-component split
            detection_method="comment",
        )
        # GhostComp exists but has no JSX
        ghost = ExtractedComponent("GhostComp", "card", "", 1, "", [], [], [], [])
        chunks = chunk_extracted_data(
            [screen],
            {"TestPage": [section]},
            {"GhostComp": ghost},
            max_chars=12_000,
        )
        comp_chunks = [c for c in chunks if c.level == "component"]
        for c in comp_chunks:
            assert c.content.strip()  # must have non-empty fallback content
