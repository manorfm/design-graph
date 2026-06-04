"""Tests for build_graph.py — pure extraction and utility functions."""
import shutil
import pytest
from pathlib import Path
from build_graph import (
    hid,
    norm_color,
    infer_type,
    sanitize_jsx,
    extract_screen_map,
    extract_all_components,
    extract_tokens,
    extract_styles,
    extract_interactions,
    extract_texts,
    diff_state,
    load_sources,
    build,
)

FIXTURE = Path(__file__).parent / "fixtures" / "simple.html"


# ─────────────────────────────────────────────────────────────────────────────
# hid
# ─────────────────────────────────────────────────────────────────────────────

class TestHid:
    def test_deterministic(self):
        assert hid("test") == hid("test")

    def test_different_inputs_differ(self):
        assert hid("abc") != hid("xyz")

    def test_prefix_prepended(self):
        assert hid("x", prefix="col_").startswith("col_")

    def test_default_length_is_8(self):
        result = hid("test")
        assert len(result) == 8

    def test_custom_length(self):
        result = hid("test", length=4)
        assert len(result) == 4


# ─────────────────────────────────────────────────────────────────────────────
# norm_color
# ─────────────────────────────────────────────────────────────────────────────

class TestNormColor:
    def test_short_hex_expanded(self):
        assert norm_color("#fff") == "#ffffff"
        assert norm_color("#abc") == "#aabbcc"

    def test_full_hex_lowercased(self):
        assert norm_color("#FFB81C") == "#ffb81c"

    def test_strips_whitespace(self):
        assert norm_color("  #fff  ") == "#ffffff"

    def test_six_digit_unchanged(self):
        assert norm_color("#1a2b3c") == "#1a2b3c"


# ─────────────────────────────────────────────────────────────────────────────
# infer_type
# ─────────────────────────────────────────────────────────────────────────────

class TestInferType:
    @pytest.mark.parametrize("name,expected", [
        ("BtnPrimary",      "button"),
        ("SaveButton",      "button"),
        ("ConfirmModal",    "modal"),
        ("AlertDialog",     "modal"),
        ("SectionCard",     "card"),
        ("RestCard",        "card"),
        ("LoginForm",       "form"),
        ("SearchInput",     "form"),
        ("TabBar",          "tab"),
        ("KpiWidget",       "card"),
        ("DonutChart",      "chart"),
        ("ProfileDrawer",   "navigation"),
        ("DarkToggle",      "toggle"),
        ("MenuItemRow",     "list-item"),
        ("StatusBadge",     "badge"),
        ("HomePageScreen",  "screen"),
        ("GenericHelper",   "component"),
    ])
    def test_infer(self, name, expected):
        assert infer_type(name) == expected


# ─────────────────────────────────────────────────────────────────────────────
# sanitize_jsx
# ─────────────────────────────────────────────────────────────────────────────

class TestSanitizeJsx:
    def test_removes_long_event_handlers(self):
        jsx = "onClick={" + "x = 1; " * 12 + "}"
        assert "on[handler]" in sanitize_jsx(jsx)

    def test_keeps_short_jsx(self):
        jsx = '<Button style={{color:"red"}}>Click</Button>'
        result = sanitize_jsx(jsx)
        assert "Button" in result
        assert "Click" in result

    def test_collapses_very_long_style(self):
        long_style = "style={{" + "color:'red'," * 60 + "}}"
        result = sanitize_jsx(long_style)
        assert len(result) < len(long_style)

    def test_removes_consecutive_blank_lines(self):
        jsx = "a\n\n\n\n\nb"
        assert "\n\n\n" not in sanitize_jsx(jsx)


# ─────────────────────────────────────────────────────────────────────────────
# extract_screen_map
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractScreenMap:
    JS = """
    function RestaurantsPage() {
        return (<div><SectionCard /><BtnPrimary /></div>)
    }
    function LoginPage() {
        return (<div><LoginForm /></div>)
    }
    function NotAScreen() {
        return (<div></div>)
    }
    """

    def test_finds_page_functions(self):
        result = extract_screen_map(self.JS)
        assert "RestaurantsPage" in result or "LoginPage" in result

    def test_excludes_non_screen_functions(self):
        result = extract_screen_map(self.JS)
        assert "NotAScreen" not in result

    def test_captures_child_components(self):
        result = extract_screen_map(self.JS)
        if "RestaurantsPage" in result:
            children = result["RestaurantsPage"]
            assert any("SectionCard" in c or "Btn" in c for c in children)


# ─────────────────────────────────────────────────────────────────────────────
# extract_all_components
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractAllComponents:
    def test_finds_components(self):
        js = """
        function BtnPrimary() { return <div/> }
        function SectionCard() { return <div/> }
        function NotAComp() { return null }
        """
        result = extract_all_components(js)
        assert "BtnPrimary" in result
        assert "SectionCard" in result

    def test_excludes_react_internals(self):
        js = "function useState() {} function Fragment() {}"
        result = extract_all_components(js)
        assert "useState" not in result
        assert "Fragment" not in result


# ─────────────────────────────────────────────────────────────────────────────
# extract_tokens
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractTokens:
    JS = """
    style={{backgroundColor: '#ffb81c'}}
    style={{backgroundColor: '#ffb81c'}}
    style={{backgroundColor: '#ffb81c'}}
    style={{color: '#ffffff'}}
    style={{color: '#ffffff'}}
    style={{color: '#ffffff'}}
    style={{padding: '16px'}}
    style={{padding: '16px'}}
    style={{padding: '16px'}}
    """

    def test_finds_color_tokens(self):
        tokens = extract_tokens(self.JS)
        values = {t["value"] for t in tokens if t["category"] == "color"}
        assert "#ffb81c" in values

    def test_finds_spacing_tokens(self):
        tokens = extract_tokens(self.JS)
        categories = {t["category"] for t in tokens}
        assert "spacing" in categories

    def test_all_tokens_have_required_fields(self):
        tokens = extract_tokens(self.JS)
        for t in tokens:
            assert "id" in t
            assert "category" in t
            assert "label" in t
            assert "value" in t
            assert "usage" in t

    def test_usage_count_reflects_occurrences(self):
        tokens = extract_tokens(self.JS)
        primary = next((t for t in tokens if t["value"] == "#ffb81c"), None)
        assert primary is not None
        assert primary["usage"] >= 3


# ─────────────────────────────────────────────────────────────────────────────
# extract_styles
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractStyles:
    JS = """
    function BtnPrimary() {
        return (
            <button
                style={{backgroundColor: '#ffb81c', padding: '8px'}}
                onMouseEnter={e => e.target.style.backgroundColor = '#f59e0b'}
                onMouseLeave={e => e.target.style.backgroundColor = '#ffb81c'}
            />
        )
    }
    """

    def test_finds_default_styles(self):
        styles = extract_styles(self.JS, "BtnPrimary")
        states = {s["state"] for s in styles}
        assert "default" in states

    def test_finds_hover_styles(self):
        styles = extract_styles(self.JS, "BtnPrimary")
        states = {s["state"] for s in styles}
        assert "hover" in states

    def test_all_styles_have_required_fields(self):
        styles = extract_styles(self.JS, "BtnPrimary")
        for s in styles:
            assert "id" in s
            assert "state" in s
            assert "property" in s
            assert "value" in s

    def test_unknown_component_returns_empty(self):
        assert extract_styles(self.JS, "NonExistent") == []


# ─────────────────────────────────────────────────────────────────────────────
# extract_interactions
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractInteractions:
    JS = """
    function BtnPrimary() {
        return (
            <button
                style={{transition: 'all 0.2s ease'}}
                onMouseEnter={e => e.target.style.backgroundColor = '#f59e0b'}
                onMouseLeave={e => e.target.style.backgroundColor = '#ffb81c'}
            />
        )
    }
    """

    def test_finds_hover_interaction(self):
        interactions = extract_interactions(self.JS, "BtnPrimary")
        triggers = {i["trigger"] for i in interactions}
        assert "hover" in triggers

    def test_interaction_has_from_to_values(self):
        interactions = extract_interactions(self.JS, "BtnPrimary")
        hover = next((i for i in interactions if i["trigger"] == "hover"), None)
        assert hover is not None
        assert hover["to_val"] != ""
        assert hover["from_val"] != ""

    def test_unknown_component_returns_empty(self):
        assert extract_interactions(self.JS, "Ghost") == []


# ─────────────────────────────────────────────────────────────────────────────
# extract_texts
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractTexts:
    JS = """
    function RestaurantsPage() {
        return (
            <div>
                <h1>Featured Restaurants</h1>
                <button>Order Now</button>
                <input placeholder="Search restaurants..." />
            </div>
        )
    }
    """

    def test_finds_heading_text(self):
        texts = extract_texts(self.JS, "RestaurantsPage")
        contents = [t["content"] for t in texts]
        assert any("Featured" in c for c in contents)

    def test_finds_placeholder(self):
        texts = extract_texts(self.JS, "RestaurantsPage")
        types = {t["text_type"] for t in texts}
        assert "placeholder" in types

    def test_all_texts_have_required_fields(self):
        texts = extract_texts(self.JS, "RestaurantsPage")
        for t in texts:
            assert "id" in t
            assert "content" in t
            assert "text_type" in t


# ─────────────────────────────────────────────────────────────────────────────
# diff_state
# ─────────────────────────────────────────────────────────────────────────────

class TestDiffState:
    def test_first_build_detected(self):
        diff = diff_state({}, {"HomeScreen": []}, {"Btn": 1})
        assert diff["is_first_build"] is True

    def test_added_screens_detected(self):
        prev = {"html_hash": "abc", "screens": {"A": "x"}, "components": {}}
        diff = diff_state(prev, {"A": [], "B": []}, {})
        assert "B" in diff["screens_added"]

    def test_removed_screens_detected(self):
        prev = {"html_hash": "abc", "screens": {"A": "x", "B": "y"}, "components": {}}
        diff = diff_state(prev, {"A": []}, {})
        assert "B" in diff["screens_removed"]

    def test_added_components_detected(self):
        from collections import Counter
        prev = {"html_hash": "abc", "screens": {}, "components": {"Btn": 2}}
        diff = diff_state(prev, {}, Counter({"Btn": 2, "NewCard": 1}))
        assert "NewCard" in diff["comps_added"]


# ─────────────────────────────────────────────────────────────────────────────
# Integration: load_sources + build (requires kuzu)
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadSources:
    def test_extracts_js_from_fixture(self):
        sources = load_sources(FIXTURE)
        assert "js" in sources
        assert "html_hash" in sources
        assert len(sources["js"]) > 0

    def test_hash_is_deterministic(self):
        a = load_sources(FIXTURE)
        b = load_sources(FIXTURE)
        assert a["html_hash"] == b["html_hash"]


class TestBuildIntegration:
    def test_build_creates_database(self, tmp_path):
        db_path = tmp_path / "test.db"
        build(FIXTURE, db_path)
        assert db_path.exists()

    def test_build_skips_unchanged_file(self, tmp_path, capsys):
        db_path = tmp_path / "test.db"
        build(FIXTURE, db_path)
        build(FIXTURE, db_path)  # second run — should skip
        out = capsys.readouterr().out
        assert "não mudou" in out or "unchanged" in out.lower() or "não mudou" in out

    def test_build_force_rebuilds(self, tmp_path):
        db_path = tmp_path / "test.db"
        build(FIXTURE, db_path)
        # Simulate --force: remove state so hash check fails, remove DB so schema creation succeeds
        (tmp_path / ".graph-state.json").unlink(missing_ok=True)
        if db_path.is_dir():
            shutil.rmtree(str(db_path))
        else:
            db_path.unlink(missing_ok=True)
        build(FIXTURE, db_path)
        assert db_path.exists()

    def test_build_finds_screens(self, tmp_path):
        import kuzu
        db_path = tmp_path / "test.db"
        build(FIXTURE, db_path)
        db = kuzu.Database(str(db_path), read_only=True)
        conn = kuzu.Connection(db)
        result = conn.execute("MATCH (s:Screen) RETURN count(s)")
        count = result.get_next()[0]
        assert count >= 1

    def test_build_finds_components(self, tmp_path):
        import kuzu
        db_path = tmp_path / "test.db"
        build(FIXTURE, db_path)
        db = kuzu.Database(str(db_path), read_only=True)
        conn = kuzu.Connection(db)
        result = conn.execute("MATCH (c:Component) RETURN count(c)")
        count = result.get_next()[0]
        assert count >= 1

    def test_build_finds_tokens(self, tmp_path):
        import kuzu
        db_path = tmp_path / "test.db"
        build(FIXTURE, db_path)
        db = kuzu.Database(str(db_path), read_only=True)
        conn = kuzu.Connection(db)
        result = conn.execute("MATCH (t:Token) RETURN count(t)")
        count = result.get_next()[0]
        assert count >= 1
