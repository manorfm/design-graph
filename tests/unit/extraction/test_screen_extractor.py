"""Tests for screen_extractor — T07."""

import pytest

from design_graph.extraction.screen_extractor import ScreenIdentity, ScreenRole, extract_screens, is_screen
from design_graph.parsing.js_parser import find_all_boundaries


class TestScreenRoleStrBehavior:
    def test_str_produces_plain_value_not_class_dot_member(self):
        # A bare (str, Enum) renders "ScreenRole.PAGE" via str()/f-string —
        # Enum.__str__ shadows str.__str__. ScreenRole must use the shared
        # StrEnum base (core/models.py) like every other enum in the domain,
        # not redefine the same footgun independently.
        assert str(ScreenIdentity.classify("RestaurantsPage").role) == "page"


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


class TestIsScreenRecognisesOverlayShellsByStructure:
    """
    ScreenIdentity's suffix table deliberately excludes Tab/Panel/Modal/...
    (C17 — "usually reusable UI parts, not navigation surfaces") and this
    stays untouched. But a full-page editor shell that conditionally
    switches between 2+ of its own Tab-suffixed children (an overlay like
    ItemEditorV6) is exactly the kind of screen an agent needs whole to
    check visual parity — recognised here by structure, never by name.
    """

    OVERLAY_JS = """
    function ItemEditorV6({ tab }) {
        return (
            <div>
                {tab === 'basic' && <BasicTab />}
                {tab === 'comp' && <CompTab />}
            </div>
        )
    }
    """

    def test_two_or_more_conditional_tabs_is_a_screen(self):
        assert is_screen("ItemEditorV6", body=self.OVERLAY_JS) is True

    def test_a_single_conditional_tab_is_not_enough(self):
        js = "function Wrapper() { return (<div>{tab==='basic' && <BasicTab/>}</div>) }"
        assert is_screen("Wrapper", body=js) is False

    def test_call_without_body_keeps_pure_name_based_classification(self):
        # Every existing caller that only has a name (no body yet) must
        # keep getting the same classification as before this change.
        assert is_screen("ItemEditorV6") is False


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

    def test_overlay_shell_is_extracted_as_a_screen_with_its_tab_refs(self):
        screens = self._screens(TestIsScreenRecognisesOverlayShellsByStructure.OVERLAY_JS)
        names = {s.name for s in screens}
        assert "ItemEditorV6" in names
        editor = next(s for s in screens if s.name == "ItemEditorV6")
        assert "BasicTab" in editor.component_refs
        assert "CompTab" in editor.component_refs

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


class TestScreenJsxSnippet:
    """
    get_full_jsx('ItemEditorV6') failed outright — reader.get_full_jsx only
    ever queried :Component nodes, and a full-page overlay shell like
    ItemEditorV6 is classified as a Screen and (deliberately) never also
    extracted as a Component (coordinator.extract_react: "a screen boundary
    must never also be extracted as a component"), so its own root JSX —
    the shell: header, grid, chrome around the tabs — was never captured by
    anything. A Screen must carry its own jsx_snippet the same way an
    ExtractedComponent does, independent of that partition.
    """

    def _screens(self, js: str):
        bounds = find_all_boundaries(js)
        return extract_screens(js, bounds)

    def test_screen_captures_its_own_return_block_as_jsx_snippet(self):
        screens = self._screens(SCREENS_JS)
        rest_page = next(s for s in screens if s.name == "RestaurantsPage")
        assert "SectionCard" in rest_page.jsx_snippet
        assert "BtnPrimary" in rest_page.jsx_snippet

    def test_overlay_shell_screen_also_captures_jsx_snippet(self):
        screens = self._screens(TestIsScreenRecognisesOverlayShellsByStructure.OVERLAY_JS)
        editor = next(s for s in screens if s.name == "ItemEditorV6")
        assert editor.jsx_snippet != ""
        assert "BasicTab" in editor.jsx_snippet

    def test_empty_js_yields_no_snippet_crash(self):
        assert extract_screens("", []) == []
