"""
Unit tests for pipeline/state.py — build-state persistence layer.

Responsibility under test: load/save/construct BuildState objects from disk.
Pure diff logic (compute_diff, compute_screen_hash) is tested in test_schema_and_diff.py.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from design_graph.core.models import BuildState, ExtractedScreen
from design_graph.pipeline.state import build_new_state, load_build_state, save_build_state


# ── helpers ───────────────────────────────────────────────────────────────────

def _screen(name: str, refs: list[str] | None = None) -> ExtractedScreen:
    return ExtractedScreen(name=name, component_refs=refs or [], sections_count=0)


def _minimal_state(**overrides) -> BuildState:
    defaults = dict(html_hash="abc123", last_build="2024-01-01T00:00:00+00:00",
                    screens={}, components={})
    return BuildState(**{**defaults, **overrides})


# ── load_build_state ──────────────────────────────────────────────────────────

class TestLoadBuildState:
    def test_returns_empty_state_when_file_missing(self, tmp_path):
        state = load_build_state(tmp_path / "nonexistent.json")
        assert state.html_hash == ""
        assert state.screens == {}
        assert state.components == {}

    def test_empty_state_has_empty_last_build(self, tmp_path):
        state = load_build_state(tmp_path / "nonexistent.json")
        assert state.last_build == ""

    def test_loads_valid_state_file(self, tmp_path):
        data = {
            "html_hash": "deadbeef",
            "last_build": "2024-06-01T12:00:00+00:00",
            "screens": {"RestaurantsPage": "hash_abc"},
            "components": {"SectionCard": 3, "BtnPrimary": 7},
        }
        path = tmp_path / "state.json"
        path.write_text(json.dumps(data), encoding="utf-8")

        state = load_build_state(path)

        assert state.html_hash == "deadbeef"
        assert state.screens == {"RestaurantsPage": "hash_abc"}
        assert state.components == {"SectionCard": 3, "BtnPrimary": 7}

    def test_returns_empty_state_for_malformed_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not {{{ valid json", encoding="utf-8")

        state = load_build_state(path)

        assert state.html_hash == ""

    def test_returns_empty_state_for_missing_keys(self, tmp_path):
        path = tmp_path / "partial.json"
        path.write_text(json.dumps({}), encoding="utf-8")

        state = load_build_state(path)

        assert state.html_hash == ""
        assert state.screens == {}

    def test_never_raises_on_any_file_content(self, tmp_path):
        for content in ["", "null", "[]", "{}", "true", "12345"]:
            path = tmp_path / "state.json"
            path.write_text(content, encoding="utf-8")
            load_build_state(path)  # must not raise


# ── save_build_state ──────────────────────────────────────────────────────────

class TestSaveBuildState:
    def test_creates_file_at_given_path(self, tmp_path):
        path = tmp_path / "state.json"
        save_build_state(path, _minimal_state())
        assert path.exists()

    def test_creates_intermediate_directories(self, tmp_path):
        path = tmp_path / "nested" / "deep" / "state.json"
        save_build_state(path, _minimal_state())
        assert path.exists()

    def test_written_file_is_valid_json(self, tmp_path):
        path = tmp_path / "state.json"
        save_build_state(path, _minimal_state())
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_roundtrip_preserves_all_fields(self, tmp_path):
        original = BuildState(
            html_hash="cafebabe",
            last_build="2025-01-15T08:30:00+00:00",
            screens={"Home": "hash_home", "Detail": "hash_detail"},
            components={"Card": 4, "Btn": 12},
        )
        path = tmp_path / "state.json"
        save_build_state(path, original)
        restored = load_build_state(path)

        assert restored.html_hash == original.html_hash
        assert restored.last_build == original.last_build
        assert restored.screens == original.screens
        assert restored.components == original.components

    def test_overwrites_existing_file(self, tmp_path):
        path = tmp_path / "state.json"
        save_build_state(path, _minimal_state(html_hash="first"))
        save_build_state(path, _minimal_state(html_hash="second"))

        state = load_build_state(path)
        assert state.html_hash == "second"


# ── build_new_state ───────────────────────────────────────────────────────────

class TestBuildNewState:
    def test_stores_provided_html_hash(self):
        state = build_new_state("abc123", [], Counter())
        assert state.html_hash == "abc123"

    def test_last_build_is_iso_utc_string(self):
        state = build_new_state("x", [], Counter())
        assert "T" in state.last_build
        assert state.last_build.endswith("+00:00")

    def test_screens_keyed_by_name(self):
        screens = [_screen("Home", ["Btn"]), _screen("Detail", ["Card"])]
        state = build_new_state("x", screens, Counter())
        assert "Home" in state.screens
        assert "Detail" in state.screens

    def test_screen_hash_is_12_char_hex(self):
        screens = [_screen("Page", ["Btn", "Card"])]
        state = build_new_state("x", screens, Counter())
        h = state.screens["Page"]
        assert len(h) == 12
        int(h, 16)  # must be valid hex

    def test_components_reflect_counter(self):
        counter = Counter({"SectionCard": 5, "BtnPrimary": 10})
        state = build_new_state("x", [], counter)
        assert state.components["SectionCard"] == 5
        assert state.components["BtnPrimary"] == 10

    def test_empty_inputs_produce_valid_state(self):
        state = build_new_state("", [], Counter())
        assert state.screens == {}
        assert state.components == {}

    def test_same_screens_produce_same_hashes(self):
        screens = [_screen("Home", ["A", "B"])]
        state_a = build_new_state("x", screens, Counter())
        state_b = build_new_state("x", screens, Counter())
        assert state_a.screens["Home"] == state_b.screens["Home"]
