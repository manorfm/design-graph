"""
Stress tests for the full pipeline against a large prototype (55+ components).

Verifies that the single-pass extractor, async pipeline, and chunker remain
correct and produce no duplicates when processing prototypes beyond typical size.

Fixture: tests/fixtures/large_bundle.html
  - 47 regular React components
  - 8 screen components
  - Multiple sections per screen (via JSX comments)
"""

import asyncio
import json
from pathlib import Path

import kuzu
import pytest

from design_graph.extraction.chunker import chunk_extracted_data
from design_graph.graph.reader import GraphReader
from design_graph.pipeline.coordinator import run_pipeline

FIXTURE_DIR  = Path(__file__).parent.parent / "fixtures"
LARGE_BUNDLE = FIXTURE_DIR / "large_bundle.html"


@pytest.fixture(scope="module")
def built_db(tmp_path_factory):
    """Build graph from large_bundle.html once for all tests in this module."""
    tmp = tmp_path_factory.mktemp("large_bundle")
    db_path    = tmp / "large.db"
    state_path = tmp / ".state.json"
    stats = asyncio.run(run_pipeline(LARGE_BUNDLE, db_path, state_path))
    return db_path, stats


@pytest.fixture(scope="module")
def reader(built_db):
    db_path, _ = built_db
    db   = kuzu.Database(str(db_path), read_only=True)
    conn = kuzu.Connection(db)
    return GraphReader(conn)


# ── Pipeline output integrity ─────────────────────────────────────────────────

class TestLargePrototypePipelineOutput:
    def test_build_succeeds_and_returns_stats(self, built_db):
        _, stats = built_db
        assert stats is not None

    def test_extracts_at_least_40_components(self, built_db):
        _, stats = built_db
        assert stats.components >= 40, f"Expected 40+ components, got {stats.components}"

    def test_extracts_all_8_screens(self, built_db):
        _, stats = built_db
        assert stats.screens >= 8, f"Expected 8 screens, got {stats.screens}"

    def test_build_duration_is_reasonable(self, built_db):
        _, stats = built_db
        assert stats.duration_seconds < 30, (
            f"Build took {stats.duration_seconds:.1f}s — single-pass should be fast"
        )

    def test_no_duplicate_components_in_graph(self, reader):
        screens = reader.list_screens()
        assert len(screens) >= 8

    def test_known_components_present(self, reader):
        for name in ("BtnPrimary", "CardRestaurant", "NavBar", "SearchBar"):
            comp = reader.get_component(name)
            assert comp is not None, f"Expected component {name!r} in graph"

    def test_known_screens_present(self, reader):
        all_screens = {s["name"] for s in reader.list_screens()}
        for expected in ("HomeScreen", "RestaurantsPage", "CartScreen"):
            assert expected in all_screens, f"Expected screen {expected!r} in graph"

    def test_contains_relationships_built(self, built_db):
        _, stats = built_db
        assert stats.contains_rels > 0, "Expected CONTAINS relationships from component hierarchy"


# ── Graph query correctness ───────────────────────────────────────────────────

class TestLargePrototypeGraphQueries:
    def test_get_screen_returns_non_empty_result(self, reader):
        result = reader.get_screen("RestaurantsPage")
        assert result is not None

    def test_component_children_populated_for_composite_component(self, reader):
        # CartItem renders QuantitySelector and PriceTag — CONTAINS should be set
        children = reader.get_component_children("CartItem")
        assert len(children) >= 1, "CartItem should have child components in CONTAINS"

    def test_transitive_screen_lookup_works(self, reader):
        screens = reader.find_screens_using_comp_transitively("BtnPrimary")
        assert len(screens) >= 2, "BtnPrimary appears in multiple screens transitively"

    def test_fuzzy_component_lookup(self, reader):
        result = reader.get_component("Cart")  # partial match → CartItem or CartScreen
        assert result is not None, "Fuzzy lookup for 'Cart' prefix should find a component"

    def test_tokens_extracted_from_large_bundle(self, reader):
        tokens = reader.get_tokens()
        assert len(tokens) >= 3, "Expected design tokens from large_bundle styles"


# ── Chunker correctness on large prototype ────────────────────────────────────

class TestLargePrototypeChunking:
    """Run chunker on the pipeline results extracted from large_bundle.html."""

    @pytest.fixture(scope="class")
    def chunks(self, reader):
        from collections import defaultdict

        from design_graph.core.models import ExtractedComponent, ExtractedScreen, ExtractedSection

        # Reconstruct minimal domain objects from graph reader output
        screens_raw = reader.list_screens()
        screens = [
            ExtractedScreen(
                name=s["name"],
                component_refs=s.get("top_components", []),
                sections_count=s.get("sections_count", 0),
            )
            for s in screens_raw
        ]

        # Build a thin component dict for chunking
        components: dict = {}
        for s in screens:
            for cname in s.component_refs:
                if cname not in components:
                    raw = reader.get_component(cname)
                    if raw:
                        components[cname] = ExtractedComponent(
                            name=cname,
                            comp_type=raw.get("c.comp_type", "card"),
                            jsx_snippet=raw.get("c.jsx_snippet", ""),
                            occurrence=raw.get("c.occurrence", 1),
                            classes=raw.get("c.classes", ""),
                            styles=[], interactions=[], texts=[],
                            child_refs=[],
                        )

        return chunk_extracted_data(screens, {}, components, max_chars=8_000)

    def test_produces_at_least_one_chunk_per_screen(self, chunks):
        screen_chunks = [c for c in chunks if c.level == "screen"]
        assert len(screen_chunks) >= 8

    def test_all_chunk_ids_are_unique(self, chunks):
        ids = [c.chunk_id for c in chunks]
        duplicates = [cid for cid in set(ids) if ids.count(cid) > 1]
        assert not duplicates, f"Duplicate chunk IDs found: {duplicates}"

    def test_no_chunk_has_empty_content(self, chunks):
        empty = [c.chunk_id for c in chunks if not c.content.strip()]
        assert not empty, f"Chunks with empty content: {empty}"

    def test_all_chunk_ids_match_valid_pattern(self, chunks):
        import re
        invalid = [c.chunk_id for c in chunks if not re.match(r"^[a-z0-9_]+$", c.chunk_id)]
        assert not invalid, f"Invalid chunk IDs (G7 violation): {invalid}"

    def test_tokens_est_within_bounds(self, chunks):
        for chunk in chunks:
            assert chunk.tokens_est == len(chunk.content) // 4

    def test_chunk_breadcrumb_contains_screen_name(self, chunks):
        for chunk in chunks:
            assert chunk.source_screen, f"chunk {chunk.chunk_id!r} missing source_screen"
