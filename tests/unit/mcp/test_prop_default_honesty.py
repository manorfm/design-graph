"""
Every props table (get_component_props, get_screen_full, get_component_spec)
used to render a "Required" column derived from PropDefault.is_required —
true whenever a prop had no default in its destructured signature. JSX has
no required/optional prop system: Btn's own real-world usage passes `icon`,
`label`, `small` and `disabled` at different call sites without ever
supplying all of them, none of which have declared defaults — so that
column asserted something the extractor cannot actually know. All three
render sites shared one _props_table_lines() helper so the fix (and this
coverage) only has to exist once.
"""

from __future__ import annotations

from design_graph.mcp.tools import ToolDispatcher, _props_table_lines


class TestPropsTableLines:
    def test_declared_default_renders_backticked_value(self):
        lines = _props_table_lines([{"prop_name": "variant", "default_value": "secondary"}])
        assert "| `variant` | `secondary` |" in lines

    def test_missing_default_renders_a_dash(self):
        lines = _props_table_lines([{"prop_name": "icon", "default_value": ""}])
        assert "| `icon` | — |" in lines

    def test_has_no_required_column(self):
        lines = "\n".join(_props_table_lines([{"prop_name": "icon", "default_value": ""}]))
        assert "Required" not in lines

    def test_includes_one_honesty_note_regardless_of_prop_count(self):
        props = [{"prop_name": f"p{i}", "default_value": ""} for i in range(5)]
        lines = "\n".join(_props_table_lines(props))
        assert lines.count("required") == 1  # the note, not a per-row marker


class _PropsReader:
    """One component with a mix of declared and undeclared prop defaults —
    exercised through all three render paths that show a props table."""

    _PROPS = [
        {"prop_name": "icon",    "default_value": ""},
        {"prop_name": "variant", "default_value": "secondary"},
    ]

    def get_component_props(self, name):
        return self._PROPS

    def get_screen_full(self, name):
        return {
            "name": "Screen", "component_count": 1, "sections_count": 0,
            "sections": [],
            "components": [{
                "name": "Btn", "comp_type": "button", "occurrence": 1,
                "jsx_snippet": "", "classes": "",
                "styles_by_state": {}, "tokens": [], "texts": [],
                "interactions": [], "props": self._PROPS, "children": [],
            }],
        }

    def get_component_spec(self, name):
        return {
            "c.name": "Btn", "c.comp_type": "button", "c.occurrence": 1,
            "c.jsx_snippet": "", "c.classes": "",
            "screens_using": [], "parents": [], "children": [],
            "styles_by_state": {}, "tokens": [], "texts": [], "interactions": [],
            "props": self._PROPS,
        }


class TestPropsRenderSitesAgreeOnHonesty:
    """Same assertions, all three tools — one shared helper means one fix."""

    def _dispatcher(self):
        return ToolDispatcher([("proto", _PropsReader())])

    def test_get_component_props_has_no_required_column(self):
        out = self._dispatcher().dispatch("get_component_props", {"name": "Btn"}, "proto")
        assert "Required" not in out
        assert "| `icon` | — |" in out
        assert "| `variant` | `secondary` |" in out

    def test_get_screen_full_has_no_required_column(self):
        out = self._dispatcher().dispatch("get_screen_full", {"name": "Screen"}, "proto")
        assert "Required" not in out
        assert "| `icon` | — |" in out
        assert "| `variant` | `secondary` |" in out

    def test_get_component_spec_has_no_required_column(self):
        out = self._dispatcher().dispatch("get_component_spec", {"name": "Btn"}, "proto")
        assert "Required" not in out
        assert "| `icon` | — |" in out
        assert "| `variant` | `secondary` |" in out
