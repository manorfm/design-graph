"""Tests for extraction/chunker.py — T16."""

import json
import re
from pathlib import Path

import pytest

from design_graph.core.models import (
    ChunkEnvelope,
    ExtractedComponent,
    ExtractedScreen,
    ExtractedSection,
)
from design_graph.extraction.chunker import (
    chunk_extracted_data,
    export_chunks_jsonl,
    to_chunk_id,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _screen(name: str, refs: list[str] | None = None) -> ExtractedScreen:
    return ExtractedScreen(name=name, component_refs=refs or [], sections_count=0)


def _section(name: str, screen: str, jsx: str = "<div>section</div>",
             refs: list[str] | None = None) -> ExtractedSection:
    return ExtractedSection(
        id=f"sec_{name.lower()}", screen=screen, name=name,
        styles={}, component_refs=refs or [], texts=[f"Text in {name}"],
        jsx_snippet=jsx, detection_method="comment",
    )


def _comp(name: str, jsx: str = "<div>comp</div>") -> ExtractedComponent:
    return ExtractedComponent(
        name=name, comp_type="card", jsx_snippet=jsx,
        occurrence=1, classes="", styles=[], interactions=[], texts=[], child_refs=[],
    )


# ── to_chunk_id ───────────────────────────────────────────────────────────────

class TestToChunkId:
    def test_pascal_case_to_snake(self):
        assert to_chunk_id("RestaurantsPage") == "restaurants_page"

    def test_double_underscore_separator_preserved(self):
        result = to_chunk_id("Page__Section")
        assert "page" in result and "section" in result

    def test_result_only_valid_chars(self):
        for input_str in ["Tela com Espaços!", "Modal#2", "Café > Header"]:
            cid = to_chunk_id(input_str)
            assert re.match(r"^[a-z0-9_]+$", cid), f"Invalid chunk_id: {cid!r}"

    def test_empty_string_gives_chunk(self):
        assert to_chunk_id("") == "chunk"

    def test_special_chars_stripped(self):
        cid = to_chunk_id("Hello World!")
        assert " " not in cid
        assert "!" not in cid


# ── chunk_extracted_data ──────────────────────────────────────────────────────

class TestChunkExtractedData:
    SCREEN = _screen("RestaurantsPage", ["SectionCard", "BtnPrimary"])
    SECTION_SMALL = _section("Header", "RestaurantsPage",
                             "<div>header content here</div>", ["BtnFilter"])
    SECTION_LARGE = _section("Lista", "RestaurantsPage",
                             "X" * 15_000, ["SectionCard"])

    def test_screen_without_sections_generates_one_chunk(self):
        screen = _screen("SimplePage", ["BtnPrimary"])
        comps = {"BtnPrimary": _comp("BtnPrimary", "<button>OK</button>")}
        chunks = chunk_extracted_data([screen], {}, comps)
        screen_chunks = [c for c in chunks if c.level == "screen"]
        assert len(screen_chunks) == 1

    def test_small_section_generates_section_chunk(self):
        chunks = chunk_extracted_data(
            [self.SCREEN],
            {"RestaurantsPage": [self.SECTION_SMALL]},
            {},
        )
        sec_chunks = [c for c in chunks if c.level == "section"]
        assert len(sec_chunks) >= 1
        assert any("Header" in c.breadcrumb for c in sec_chunks)

    def test_large_section_splits_into_component_chunks(self):
        comps = {"SectionCard": _comp("SectionCard", "<div>card content</div>")}
        chunks = chunk_extracted_data(
            [self.SCREEN],
            {"RestaurantsPage": [self.SECTION_LARGE]},
            comps,
            max_chars=12_000,
        )
        comp_chunks = [c for c in chunks if c.level == "component"]
        assert len(comp_chunks) >= 1

    def test_all_chunk_ids_are_unique(self):
        chunks = chunk_extracted_data(
            [self.SCREEN],
            {"RestaurantsPage": [self.SECTION_SMALL, self.SECTION_LARGE]},
            {"SectionCard": _comp("SectionCard")},
        )
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids)), f"Duplicate IDs: {[i for i in ids if ids.count(i) > 1]}"

    def test_no_empty_content_chunks(self):
        chunks = chunk_extracted_data(
            [self.SCREEN],
            {"RestaurantsPage": [self.SECTION_SMALL]},
            {},
        )
        assert all(c.content for c in chunks), "Found chunk with empty content"

    def test_parent_id_links_section_to_screen(self):
        chunks = chunk_extracted_data(
            [self.SCREEN],
            {"RestaurantsPage": [self.SECTION_SMALL]},
            {},
        )
        sec_chunk = next(c for c in chunks if c.level == "section")
        screen_chunk = next(c for c in chunks if c.level == "screen")
        assert sec_chunk.parent_id == screen_chunk.chunk_id

    def test_sibling_ids_populated_for_multiple_sections(self):
        sec2 = _section("Filtros", "RestaurantsPage", "<div>filtros</div>", ["FilterBtn"])
        chunks = chunk_extracted_data(
            [self.SCREEN],
            {"RestaurantsPage": [self.SECTION_SMALL, sec2]},
            {},
        )
        header_chunk = next(c for c in chunks if "header" in c.chunk_id.lower())
        filtros_chunk = next(c for c in chunks if "filtros" in c.chunk_id.lower())
        assert filtros_chunk.chunk_id in header_chunk.sibling_ids
        assert header_chunk.chunk_id in filtros_chunk.sibling_ids

    def test_tokens_est_does_not_exceed_max_chars_over_4(self):
        chunks = chunk_extracted_data(
            [self.SCREEN],
            {"RestaurantsPage": [self.SECTION_SMALL]},
            {},
            max_chars=12_000,
        )
        for chunk in chunks:
            assert chunk.tokens_est <= 12_000 // 4

    def test_multiple_screens_handled(self):
        screen2 = _screen("LoginForm", ["InputField", "BtnPrimary"])
        chunks = chunk_extracted_data([self.SCREEN, screen2], {}, {})
        screen_names = {c.source_screen for c in chunks}
        assert "RestaurantsPage" in screen_names
        assert "LoginForm" in screen_names

    def test_empty_screens_returns_empty_list(self):
        assert chunk_extracted_data([], {}, {}) == []


# ── export_chunks_jsonl ───────────────────────────────────────────────────────

class TestExportChunksJsonl:
    def _make_chunk(self, cid: str) -> ChunkEnvelope:
        return ChunkEnvelope(
            chunk_id=cid, breadcrumb=f"Pg > {cid}", level="section",
            parent_id="pg", sibling_ids=[], child_ids=[],
            content=f"<div>{cid}</div>", tokens_est=5,
            component_refs=[], context_summary="test", source_screen="Pg",
        )

    def test_creates_file(self, tmp_path):
        output = tmp_path / "out.jsonl"
        export_chunks_jsonl([self._make_chunk("id_1")], output)
        assert output.exists()

    def test_one_line_per_chunk(self, tmp_path):
        output = tmp_path / "out.jsonl"
        export_chunks_jsonl([self._make_chunk("a"), self._make_chunk("b")], output)
        lines = output.read_text().splitlines()
        assert len(lines) == 2

    def test_each_line_is_valid_json(self, tmp_path):
        output = tmp_path / "out.jsonl"
        export_chunks_jsonl([self._make_chunk("c"), self._make_chunk("d")], output)
        for line in output.read_text().splitlines():
            data = json.loads(line)
            assert "chunk_id" in data

    def test_empty_list_creates_empty_file(self, tmp_path):
        output = tmp_path / "empty.jsonl"
        export_chunks_jsonl([], output)
        assert output.read_text() == ""

    def test_creates_parent_directory(self, tmp_path):
        output = tmp_path / "sub" / "dir" / "out.jsonl"
        export_chunks_jsonl([self._make_chunk("e")], output)
        assert output.exists()
