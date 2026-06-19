"""Tests for screen_extractor — T07."""

import pytest

from design_graph.extraction.screen_extractor import extract_screens, is_screen
from design_graph.parsing.js_parser import find_all_boundaries


class TestIsScreen:
    @pytest.mark.parametrize("name,expected", [
        ("RestaurantsPage",   True),
        ("OrdersDashboard",   True),
        ("MenuSection",       False),
        ("ItemDetail",        True),
        ("LoginForm",         True),
        ("ProfileModal",      False),
        ("KitchenView",       True),
        ("BillList",          False),
        ("BtnPrimary",        False),
        ("SectionCard",       False),
        ("useRestaurants",    False),
        ("Fragment",          False),
        ("A",                 False),  # too short
        ("RestaurantsPageHelper", False),  # doesn't end in keyword
    ])
    def test_is_screen_classification(self, name, expected):
        assert is_screen(name) == expected


SCREENS_JS = """
function RestaurantsPage() {
    return (
        <div>
            <SectionCard restaurant={r} />
            <BtnPrimary onClick={handleOrder} />
            <ConfirmModal isOpen={open} />
        </div>
    )
}
function LoginForm() {
    return (
        <form>
            <Input name="email" />
            <BtnPrimary type="submit" />
        </form>
    )
}
function BtnPrimary() {
    return (<button>OK</button>)
}
"""


class TestExtractScreens:
    def _screens(self, js: str):
        bounds = find_all_boundaries(js)
        return extract_screens(js, bounds)

    def test_finds_page_screens(self):
        screens = self._screens(SCREENS_JS)
        names = {s.name for s in screens}
        assert "RestaurantsPage" in names
        assert "LoginForm" in names

    def test_excludes_non_screens(self):
        screens = self._screens(SCREENS_JS)
        names = {s.name for s in screens}
        assert "BtnPrimary" not in names

    def test_captures_direct_component_references(self):
        screens = self._screens(SCREENS_JS)
        rest_page = next(s for s in screens if s.name == "RestaurantsPage")
        assert "SectionCard" in rest_page.component_refs
        assert "BtnPrimary" in rest_page.component_refs
        assert "ConfirmModal" in rest_page.component_refs

    def test_screen_not_in_own_refs(self):
        screens = self._screens(SCREENS_JS)
        for screen in screens:
            assert screen.name not in screen.component_refs

    def test_react_internals_excluded_from_refs(self):
        js = "function HomePage() { return (<React.Fragment><div/></React.Fragment>) }"
        screens = self._screens(js)
        home = next((s for s in screens if s.name == "HomePage"), None)
        if home:
            assert "Fragment" not in home.component_refs
            assert "React" not in home.component_refs

    def test_component_refs_are_sorted(self):
        screens = self._screens(SCREENS_JS)
        for screen in screens:
            assert screen.component_refs == sorted(screen.component_refs)

    def test_sections_count_initialised_to_zero(self):
        screens = self._screens(SCREENS_JS)
        for screen in screens:
            assert screen.sections_count == 0

    def test_empty_js_returns_empty_list(self):
        assert extract_screens("", []) == []

    def test_no_screens_in_js_returns_empty_list(self):
        js = "function BtnPrimary() { return <div/>; }"
        screens = self._screens(js)
        assert screens == []

    def test_screen_named_function_without_visual_return_is_rejected(self):
        js = "function SettingsPage() { return calculateSettings(); }"
        assert self._screens(js) == []
