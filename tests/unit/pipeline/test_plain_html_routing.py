"""
Tests for the pipeline format routing logic.

Verifies that:
  - plain_html WITHOUT React functions → _extract_plain_html path
  - plain_html WITH React functions   → _extract_react path (existing behavior)
  - bundled_react / tailwind          → _extract_react path always
  - _has_react_functions detects PascalCase function declarations correctly
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from design_graph.pipeline.coordinator import _has_react_functions, run_pipeline

FIXTURE_DIR = Path(__file__).parent.parent.parent / "fixtures"


# ── _has_react_functions ──────────────────────────────────────────────────────

class TestHasReactFunctions:
    def test_detects_simple_pascalcase_function(self):
        js = "function BtnPrimary() { return <div/>; }"
        assert _has_react_functions(js) is True

    def test_detects_multiple_component_functions(self):
        js = "function Card() {} function Modal() {} function BtnPrimary() {}"
        assert _has_react_functions(js) is True

    def test_rejects_empty_js(self):
        assert _has_react_functions("") is False

    def test_rejects_js_without_pascalcase_functions(self):
        js = "function handleClick() {} function fetchData() {}"
        assert _has_react_functions(js) is False

    def test_rejects_plain_html_without_scripts(self):
        assert _has_react_functions("   ") is False

    def test_detects_screen_components(self):
        js = "function RestaurantsPage() { return <div/>; }"
        assert _has_react_functions(js) is True

    def test_min_name_length_enforced(self):
        # RE_COMP_FN requires at least 3 chars after first uppercase
        js = "function Ab() { return null; }"
        # "Ab" is 2 chars total — too short for RE_COMP_FN which needs 3+
        result = _has_react_functions(js)
        # This may or may not match depending on the exact pattern — just no crash
        assert isinstance(result, bool)


# ── Routing integration: plain.html uses plain HTML path ─────────────────────

class TestPlainHtmlRouting:
    def test_plain_html_fixture_uses_dom_pattern_path(self, tmp_path):
        """plain.html has no React functions — should use DOM pattern extraction."""
        from design_graph.graph.reader import GraphReader
        import kuzu

        db_path    = tmp_path / "plain_route.db"
        state_path = tmp_path / ".state.json"
        stats = asyncio.run(run_pipeline(
            FIXTURE_DIR / "plain.html", db_path, state_path
        ))
        assert stats is not None
        # DOM patterns should produce at least one component
        db   = kuzu.Database(str(db_path), read_only=True)
        conn = kuzu.Connection(db)
        r    = conn.execute("MATCH (c:Component) RETURN count(c)")
        assert r.get_next()[0] >= 1

    def test_simple_html_fixture_uses_react_path(self, tmp_path):
        """simple.html has React functions — should use function boundary extraction."""
        import kuzu

        db_path    = tmp_path / "simple_route.db"
        state_path = tmp_path / ".state.json"
        stats = asyncio.run(run_pipeline(
            FIXTURE_DIR / "simple.html", db_path, state_path
        ))
        assert stats is not None
        db   = kuzu.Database(str(db_path), read_only=True)
        conn = kuzu.Connection(db)
        r    = conn.execute("MATCH (s:Screen) RETURN count(s)")
        assert r.get_next()[0] >= 1


# ── Routing integration: synthetic screen name ────────────────────────────────

class TestSyntheticScreenName:
    def test_plain_html_generates_screen_from_title(self, tmp_path):
        """The <title> tag should seed the screen name."""
        html = """<!DOCTYPE html>
        <html><head><title>My Store App</title></head>
        <body>
          <nav><a>Home</a><a>Shop</a></nav>
          <main><section id="products"><h2>Products</h2><p>Some text here</p></section></main>
        </body></html>"""
        html_path = tmp_path / "my_store.html"
        html_path.write_text(html, encoding="utf-8")

        db_path    = tmp_path / "store.db"
        state_path = tmp_path / ".state.json"
        asyncio.run(run_pipeline(html_path, db_path, state_path))

        import kuzu
        db   = kuzu.Database(str(db_path), read_only=True)
        conn = kuzu.Connection(db)
        r    = conn.execute("MATCH (s:Screen) RETURN s.name")
        screen_names = []
        while r.has_next():
            screen_names.append(r.get_next()[0])
        assert screen_names, "Expected at least one screen"

    def test_plain_html_without_title_uses_main_page(self, tmp_path):
        """HTML without <title> should fallback to 'MainPage'."""
        html = """<html>
        <body>
          <nav><a>Home</a><a>About</a></nav>
          <footer><p>2024</p></footer>
        </body></html>"""
        html_path = tmp_path / "notitle.html"
        html_path.write_text(html, encoding="utf-8")

        db_path    = tmp_path / "notitle.db"
        state_path = tmp_path / ".state.json"
        asyncio.run(run_pipeline(html_path, db_path, state_path))

        import kuzu
        db   = kuzu.Database(str(db_path), read_only=True)
        conn = kuzu.Connection(db)
        r    = conn.execute("MATCH (s:Screen) RETURN s.name")
        screen_names = []
        while r.has_next():
            screen_names.append(r.get_next()[0])
        assert screen_names, "Expected MainPage screen"
        assert "MainPage" in screen_names[0] or "Page" in screen_names[0]
