"""
Style tables truncate to a fixed row cap before rendering (get_screen_full,
get_component_spec). Without deduping by property first, a CSS property that
takes multiple literal values across conditional/mapped JSX (e.g.
`color: i === 2 ? col : 'white'`) produces several rows with the *same*
property name — these can crowd out genuinely distinct properties under the
cap, so an agent reading the table silently loses real information instead
of just seeing fewer of the same thing.
"""

from __future__ import annotations

from design_graph.mcp.tools import ToolDispatcher, _dedupe_styles_by_property


class TestDedupeStylesByProperty:
    def test_no_duplicates_returns_equivalent_list(self):
        styles = [{"property": "color", "value": "red"}, {"property": "gap", "value": "8px"}]
        assert _dedupe_styles_by_property(styles) == styles

    def test_duplicate_property_different_values_merged_into_one_row(self):
        styles = [
            {"property": "color", "value": "white"},
            {"property": "color", "value": "#f00"},
        ]
        result = _dedupe_styles_by_property(styles)
        assert len(result) == 1
        assert result[0]["property"] == "color"
        assert result[0]["value"] == "white | #f00"

    def test_duplicate_property_same_value_not_repeated_in_output(self):
        styles = [
            {"property": "color", "value": "white"},
            {"property": "color", "value": "white"},
        ]
        result = _dedupe_styles_by_property(styles)
        assert len(result) == 1
        assert result[0]["value"] == "white"

    def test_preserves_first_seen_property_order(self):
        styles = [
            {"property": "gap", "value": "8px"},
            {"property": "color", "value": "red"},
            {"property": "gap", "value": "12px"},
        ]
        result = _dedupe_styles_by_property(styles)
        assert [r["property"] for r in result] == ["gap", "color"]

    def test_empty_list_returns_empty_list(self):
        assert _dedupe_styles_by_property([]) == []


class MockReaderWithCrowdedStyles:
    """
    Reproduces the real RestCard shape found on the reference prototype:
    28 raw style rows, but only 17 distinct property names — color/fontSize/
    gap each repeated several times from conditional JSX. padding and
    gridTemplateColumns are real, distinct properties that must survive
    the 12-row cap once dedup runs first.
    """

    _RAW_DEFAULT_STYLES = (
        [{"property": "color", "value": v} for v in ("a", "b", "c", "d")]
        + [{"property": "fontSize", "value": v} for v in ("12px", "13px", "14px", "15px")]
        + [{"property": "gap", "value": v} for v in ("4px", "6px", "8px", "10px")]
        + [{"property": "alignItems", "value": "center"}]
        + [{"property": "background", "value": "#111"}]
        + [{"property": "borderRadius", "value": "8px"}]
        + [{"property": "display", "value": "grid"}]
        + [{"property": "gridTemplateColumns", "value": "repeat(3,1fr)"}]
        + [{"property": "padding", "value": "16px"}]
    )

    def get_component_spec(self, name):
        return {
            "c.name": "RestCard", "c.comp_type": "card", "c.occurrence": 1,
            "screens_using": [], "parents": [], "children": [],
            "styles_by_state": {"default": list(self._RAW_DEFAULT_STYLES)},
            "tokens": [], "texts": [], "interactions": [], "props": [],
        }

    def get_screen_full(self, name):
        return {
            "name": "RestaurantsPage", "component_count": 1, "sections_count": 0,
            "sections": [],
            "components": [{
                "name": "RestCard", "comp_type": "card", "jsx_snippet": "",
                "occurrence": 1, "classes": "",
                "styles_by_state": {"default": list(self._RAW_DEFAULT_STYLES)},
                "tokens": [], "texts": [], "interactions": [], "props": [], "children": [],
            }],
            "layout_profiles": [],
        }


class TestStyleTruncationNoLongerHidesDistinctProperties:
    def _dispatcher(self):
        return ToolDispatcher([("proto", MockReaderWithCrowdedStyles())])

    def test_get_component_spec_shows_padding_despite_28_raw_rows(self):
        output = self._dispatcher().dispatch("get_component_spec", {"name": "RestCard"}, "proto")
        assert "| padding |" in output

    def test_get_component_spec_shows_grid_template_columns(self):
        output = self._dispatcher().dispatch("get_component_spec", {"name": "RestCard"}, "proto")
        assert "| gridTemplateColumns |" in output

    def test_get_screen_full_shows_padding_for_nested_component(self):
        output = self._dispatcher().dispatch("get_screen_full", {"name": "RestaurantsPage"}, "proto")
        assert "| padding |" in output
