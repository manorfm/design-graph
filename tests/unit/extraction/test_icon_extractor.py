"""
Tests for extraction.icon_extractor.extract_icons — deduplication of inline
<svg> icon markup out of a component's raw jsx into {[icon:id]} markers.

Runs on the jsx_raw text *before* sanitize_jsx, so the icon's true source is
captured once and the marker left behind is what sanitize_jsx and every
downstream regex actually sees.
"""

from __future__ import annotations

from design_graph.core.models import IconAsset
from design_graph.extraction.icon_extractor import extract_icons


class TestExtractIconsNoSvg:
    def test_jsx_without_svg_is_returned_unchanged(self):
        jsx = "<button>Go</button>"
        result, icons = extract_icons(jsx)
        assert result == jsx
        assert icons == []


class TestExtractIconsSingleBlock:
    def test_paired_svg_tag_is_replaced_with_marker(self):
        svg = '<svg viewBox="0 0 24 24"><path d="M12 2L2 7"/></svg>'
        jsx = f"<button>{svg}Go</button>"
        result, icons = extract_icons(jsx)

        assert len(icons) == 1
        assert icons[0].markup == svg
        assert result == f"<button>{IconAsset.create(svg)}Go</button>"
        assert svg not in result

    def test_self_closing_svg_tag_is_replaced_with_marker(self):
        svg = '<svg viewBox="0 0 24 24" />'
        jsx = f"<span>{svg}</span>"
        result, icons = extract_icons(jsx)

        assert len(icons) == 1
        assert icons[0].markup == svg
        assert str(icons[0]) in result
        assert svg not in result


class TestExtractIconsDeduplication:
    def test_identical_icon_used_twice_yields_one_asset_two_markers(self):
        svg = '<svg><path d="M0 0"/></svg>'
        jsx = f"<div>{svg}<span>label</span>{svg}</div>"
        result, icons = extract_icons(jsx)

        assert len(icons) == 2
        assert icons[0].id == icons[1].id
        assert result.count(str(icons[0])) == 2

    def test_different_icons_yield_distinct_markers(self):
        svg_a = '<svg><path d="M0 0"/></svg>'
        svg_b = '<svg><path d="M1 1"/></svg>'
        jsx = f"<div>{svg_a}{svg_b}</div>"
        result, icons = extract_icons(jsx)

        assert {i.markup for i in icons} == {svg_a, svg_b}
        assert result == f"<div>{icons[0]}{icons[1]}</div>"


class TestExtractIconsNestedSvg:
    def test_sprite_defs_with_nested_svg_resolves_to_outer_closing_tag(self):
        svg = '<svg><defs><svg id="i"><path d="M0 0"/></svg></defs><use href="#i"/></svg>'
        jsx = f"<div>{svg}</div>"
        result, icons = extract_icons(jsx)

        assert len(icons) == 1
        assert icons[0].markup == svg
        assert result == f"<div>{icons[0]}</div>"


class TestExtractIconsWithinConditional:
    def test_condition_wrapper_is_preserved_around_marker(self):
        svg = '<svg><path d="M0 0"/></svg>'
        jsx = f"{{item.highlight && (<span>{svg}</span>)}}"
        result, icons = extract_icons(jsx)

        assert len(icons) == 1
        assert "item.highlight" in result
        assert str(icons[0]) in result
        assert svg not in result


class TestExtractIconsUnbalanced:
    def test_unclosed_svg_tag_is_left_untouched(self):
        jsx = "<div><svg><path d=\"M0 0\"/></div>"
        result, icons = extract_icons(jsx)

        assert result == jsx
        assert icons == []
