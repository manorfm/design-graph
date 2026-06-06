"""
Unit tests for cli/report.py — prototype documentation builder.

Tests the report building and Markdown rendering logic using a MockReader
so no Kuzu database is needed. Integration with a real graph is in
tests/integration/test_report_e2e.py.

Responsibilities under test:
  - PrototypeReport dataclass and its sub-objects
  - build_prototype_report(): builds report from GraphReader
  - render_markdown_report(): produces valid Markdown
  - ReportConfig: controls what is included in the report
"""

from __future__ import annotations

import pytest

from design_graph.cli.report import (
    ComponentSummary,
    PrototypeReport,
    ReportConfig,
    ScreenReport,
    TokenTableRow,
    build_prototype_report,
    render_markdown_report,
)


# ── Minimal mock reader ───────────────────────────────────────────────────────

class _MockReader:
    def list_screens(self):
        return [
            {"name": "RestaurantsPage", "component_count": 3,
             "sections_count": 2, "top_components": ["SearchBar", "CardRestaurant"]},
            {"name": "LoginForm", "component_count": 2,
             "sections_count": 0, "top_components": ["InputText", "BtnPrimary"]},
        ]

    def get_screen(self, name):
        if "Restaurants" in name:
            return {
                "name": "RestaurantsPage", "component_count": 3, "sections_count": 2,
                "sections": [
                    {"sec.name": "Header", "sec.components_json": '["SearchBar"]',
                     "sec.detection_method": "comment"},
                    {"sec.name": "Lista", "sec.components_json": '["CardRestaurant"]',
                     "sec.detection_method": "structural"},
                ],
                "components": [
                    {"c.name": "SearchBar",      "c.comp_type": "search"},
                    {"c.name": "CardRestaurant", "c.comp_type": "card"},
                ],
                "texts": [],
            }
        return {"name": name, "component_count": 2, "sections_count": 0,
                "sections": [], "components": [], "texts": []}

    def get_tokens(self, category=None):
        return [
            {"t.label": "primary",    "t.value": "#ffb81c", "t.category": "color",   "t.usage": 15},
            {"t.label": "background", "t.value": "#1a1a1a", "t.category": "color",   "t.usage": 8},
            {"t.label": "space_16",   "t.value": "16px",    "t.category": "spacing", "t.usage": 12},
        ]

    def get_component(self, name):
        return {"c.name": name, "c.comp_type": "card", "c.jsx_snippet": "<div/>",
                "c.occurrence": 2, "c.classes": "card",
                "styles": [], "tokens": [], "texts": [], "interactions": [],
                "screens_using": ["RestaurantsPage"], "children": []}

    def get_component_children(self, name): return []
    def count_nodes(self):
        return {"screens": 2, "components": 5, "tokens": 3, "sections": 2,
                "texts": 8, "styles": 12, "interactions": 3, "contains": 4}
    def get_impact(self, n): return {"found": False}
    def find_token_usage(self, v): return []
    def get_section(self, s, h): return None
    def get_interactions(self, n): return []
    def get_full_jsx(self, n): return ""
    def find_screens_using_comp_transitively(self, n): return []
    def get_component_parents(self, n): return []
    def get_tokens_for_category(self, cat): return []


# ── Domain object contracts ───────────────────────────────────────────────────

class TestDomainObjectContracts:
    def test_token_table_row_has_required_fields(self):
        row = TokenTableRow(category="color", label="primary",
                            value="#ffb81c", usage=15)
        assert row.category == "color"
        assert row.label == "primary"
        assert row.value == "#ffb81c"
        assert row.usage == 15

    def test_component_summary_has_required_fields(self):
        cs = ComponentSummary(name="BtnPrimary", comp_type="button",
                              occurrence=5, section_name="Header")
        assert cs.name == "BtnPrimary"
        assert cs.comp_type == "button"
        assert cs.occurrence == 5

    def test_screen_report_has_required_fields(self):
        sr = ScreenReport(name="MyPage", component_count=3, sections_count=1,
                          section_names=["Header"], component_summaries=[])
        assert sr.name == "MyPage"
        assert sr.component_count == 3

    def test_prototype_report_has_all_fields(self):
        r = PrototypeReport(
            prototype_name="myapp",
            generated_at="2026-06-07T10:00:00+00:00",
            node_counts={"screens": 2},
            token_rows=[],
            screen_reports=[],
        )
        assert r.prototype_name == "myapp"
        assert isinstance(r.token_rows, list)

    def test_report_config_defaults(self):
        cfg = ReportConfig(prototype_name="myapp")
        assert cfg.include_tokens is True
        assert cfg.include_jsx is False
        assert cfg.max_components_per_screen > 0

    def test_report_config_customizable(self):
        cfg = ReportConfig(prototype_name="myapp", include_jsx=True, include_tokens=False)
        assert cfg.include_jsx is True
        assert cfg.include_tokens is False


# ── build_prototype_report ────────────────────────────────────────────────────

class TestBuildPrototypeReport:
    def _build(self, **cfg_overrides) -> PrototypeReport:
        reader = _MockReader()
        config = ReportConfig(prototype_name="myapp", **cfg_overrides)
        return build_prototype_report(reader, config)

    def test_returns_prototype_report(self):
        assert isinstance(self._build(), PrototypeReport)

    def test_prototype_name_from_config(self):
        report = self._build()
        assert report.prototype_name == "myapp"

    def test_generated_at_is_iso_string(self):
        report = self._build()
        assert "T" in report.generated_at
        assert report.generated_at.endswith("+00:00")

    def test_node_counts_populated(self):
        report = self._build()
        assert report.node_counts.get("screens", 0) >= 1

    def test_screen_reports_match_reader_screens(self):
        report = self._build()
        assert len(report.screen_reports) == 2

    def test_screen_names_correct(self):
        report = self._build()
        names = {sr.name for sr in report.screen_reports}
        assert "RestaurantsPage" in names
        assert "LoginForm" in names

    def test_token_rows_populated_when_include_tokens_true(self):
        report = self._build(include_tokens=True)
        assert len(report.token_rows) >= 1

    def test_token_rows_empty_when_include_tokens_false(self):
        report = self._build(include_tokens=False)
        assert report.token_rows == []

    def test_token_rows_have_correct_fields(self):
        report = self._build(include_tokens=True)
        for row in report.token_rows:
            assert isinstance(row, TokenTableRow)
            assert row.label
            assert row.value
            assert row.category

    def test_section_names_included_in_screen_report(self):
        report = self._build()
        rest_page = next(sr for sr in report.screen_reports if "Restaurants" in sr.name)
        assert len(rest_page.section_names) >= 1
        assert "Header" in rest_page.section_names or "Lista" in rest_page.section_names

    def test_tokens_sorted_by_category_then_usage(self):
        report = self._build(include_tokens=True)
        colors  = [t for t in report.token_rows if t.category == "color"]
        usages  = [t.usage for t in colors]
        assert usages == sorted(usages, reverse=True)


# ── render_markdown_report ────────────────────────────────────────────────────

class TestRenderMarkdownReport:
    def _report(self) -> PrototypeReport:
        return build_prototype_report(_MockReader(), ReportConfig(prototype_name="myapp"))

    def test_returns_string(self):
        assert isinstance(render_markdown_report(self._report()), str)

    def test_starts_with_h1_heading(self):
        md = render_markdown_report(self._report())
        assert md.strip().startswith("#")

    def test_contains_prototype_name(self):
        md = render_markdown_report(self._report())
        assert "myapp" in md

    def test_contains_overview_section(self):
        md = render_markdown_report(self._report())
        assert "## Overview" in md or "Overview" in md

    def test_contains_screen_names(self):
        md = render_markdown_report(self._report())
        assert "RestaurantsPage" in md
        assert "LoginForm" in md

    def test_contains_token_table_when_tokens_present(self):
        report = build_prototype_report(
            _MockReader(), ReportConfig(prototype_name="myapp", include_tokens=True)
        )
        md = render_markdown_report(report)
        # Should have a table or token section
        assert "#ffb81c" in md or "primary" in md

    def test_no_token_table_when_include_tokens_false(self):
        report = build_prototype_report(
            _MockReader(), ReportConfig(prototype_name="myapp", include_tokens=False)
        )
        md = render_markdown_report(report)
        assert "#ffb81c" not in md

    def test_markdown_has_valid_structure(self):
        md = render_markdown_report(self._report())
        lines = md.splitlines()
        headings = [l for l in lines if l.startswith("#")]
        assert len(headings) >= 3  # overview, screens, at least one section

    def test_screen_sections_present(self):
        md = render_markdown_report(self._report())
        assert "## Screens" in md or "### RestaurantsPage" in md

    def test_component_count_shown(self):
        md = render_markdown_report(self._report())
        assert any(c.isdigit() for c in md)

    def test_section_names_shown_in_screen_section(self):
        md = render_markdown_report(self._report())
        assert "Header" in md or "Lista" in md

    def test_generated_at_present(self):
        md = render_markdown_report(self._report())
        assert "2026" in md or "Generated" in md
