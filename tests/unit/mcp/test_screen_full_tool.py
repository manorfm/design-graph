"""
TDD — get_screen_full MCP tool: comprehensive screen spec for AI screen reconstruction.

Tests that ToolDispatcher.dispatch("get_screen_full", ...) renders a complete
Markdown document covering sections, components (with styles, props, interactions,
JSX) and layout profiles — everything an AI agent needs to implement a screen.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from design_graph.graph.reader import GraphReader
from design_graph.mcp.tools import TOOL_DEFINITIONS, ToolDispatcher


# ── Shared fixture data ───────────────────────────────────────────────────────

def _make_screen_full_spec() -> dict:
    return {
        "name": "HomeScreen",
        "component_count": 2,
        "sections_count": 1,
        "sections": [
            {
                "id":               "sec1",
                "name":             "HeroSection",
                "detection_method": "comment",
                "styles":           {"padding": "32px", "backgroundColor": "#000"},
                "component_refs":   ["TopNav"],
                "texts":            ["Welcome", "Get started"],
                "jsx_snippet":      "<section>Hero</section>",
            }
        ],
        "components": [
            {
                "name":       "TopNav",
                "comp_type":  "navigation",
                "jsx_snippet": "<nav>Home</nav>",
                "occurrence": 1,
                "classes":    "nav-bar",
                "styles_by_state": {
                    "default": [{"property": "display",         "value": "flex"}],
                    "hover":   [{"property": "backgroundColor", "value": "#f0f0f0"}],
                },
                "tokens": [{"label": "primary", "value": "#007bff", "category": "color"}],
                "texts":  [{"content": "Home", "text_type": "heading", "element": "h1"}],
                "interactions": [
                    {
                        "trigger":    "hover",
                        "css_prop":   "backgroundColor",
                        "from_val":   "#fff",
                        "to_val":     "#f0f0f0",
                        "transition": "all 0.2s",
                    }
                ],
                "props": [
                    {"prop_name": "title",   "default_value": ""},
                    {"prop_name": "variant", "default_value": "default"},
                ],
                "children": ["Badge"],
            },
        ],
        "layout_profiles": [
            {
                "component_name":  "TopNav",
                "display":         "flex",
                "position":        None,
                "width":           "100%",
                "height":          None,
                "padding":         None,
                "padding_top":     None,
                "padding_right":   None,
                "padding_bottom":  None,
                "padding_left":    None,
                "margin":          None,
                "margin_top":      None,
                "margin_right":    None,
                "margin_bottom":   None,
                "margin_left":     None,
                "flex_direction":  None,
                "align_items":     "center",
                "justify_content": None,
                "gap":             None,
                "overflow":        None,
                "z_index":         None,
                "extra_layout":    {},
            }
        ],
    }


@pytest.fixture
def reader_with_full_screen():
    reader = MagicMock(spec=GraphReader)
    reader.get_screen_full.return_value = _make_screen_full_spec()
    return reader


@pytest.fixture
def dispatcher(reader_with_full_screen):
    return ToolDispatcher([("myapp", reader_with_full_screen)])


# ── Tool definition ───────────────────────────────────────────────────────────

class TestGetScreenFullToolDefinition:
    def test_tool_exists_in_tool_definitions(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "get_screen_full" in names

    def test_tool_requires_name_parameter(self):
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "get_screen_full")
        assert "name" in tool["inputSchema"]["required"]

    def test_tool_description_mentions_implementation_or_reconstruction(self):
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "get_screen_full")
        desc = tool["description"].lower()
        assert "implement" in desc or "reconstruct" in desc


# ── Dispatch ──────────────────────────────────────────────────────────────────

class TestGetScreenFullToolDispatch:
    def test_dispatches_to_reader_get_screen_full(self, dispatcher, reader_with_full_screen):
        dispatcher.dispatch("get_screen_full", {"name": "HomeScreen"}, "myapp")
        reader_with_full_screen.get_screen_full.assert_called_once_with("HomeScreen")

    def test_returns_not_found_message_for_none_reader_result(self, dispatcher, reader_with_full_screen):
        reader_with_full_screen.get_screen_full.return_value = None
        output = dispatcher.dispatch("get_screen_full", {"name": "NoScreen"}, "myapp")
        assert "not found" in output.lower() or "não encontrada" in output.lower()


# ── Rendered output — sections ────────────────────────────────────────────────

class TestGetScreenFullToolSectionOutput:
    def test_renders_screen_name_as_top_heading(self, dispatcher):
        output = dispatcher.dispatch("get_screen_full", {"name": "HomeScreen"}, "myapp")
        assert "HomeScreen" in output

    def test_renders_section_name(self, dispatcher):
        output = dispatcher.dispatch("get_screen_full", {"name": "HomeScreen"}, "myapp")
        assert "HeroSection" in output

    def test_renders_section_styles(self, dispatcher):
        output = dispatcher.dispatch("get_screen_full", {"name": "HomeScreen"}, "myapp")
        assert "32px" in output

    def test_renders_section_component_refs(self, dispatcher):
        output = dispatcher.dispatch("get_screen_full", {"name": "HomeScreen"}, "myapp")
        assert "TopNav" in output

    def test_renders_section_texts(self, dispatcher):
        output = dispatcher.dispatch("get_screen_full", {"name": "HomeScreen"}, "myapp")
        assert "Welcome" in output

    def test_renders_section_jsx(self, dispatcher):
        output = dispatcher.dispatch("get_screen_full", {"name": "HomeScreen"}, "myapp")
        assert "section" in output.lower()


# ── Rendered output — components ──────────────────────────────────────────────

class TestGetScreenFullToolComponentOutput:
    def test_renders_component_type(self, dispatcher):
        output = dispatcher.dispatch("get_screen_full", {"name": "HomeScreen"}, "myapp")
        assert "navigation" in output

    def test_renders_default_state_styles(self, dispatcher):
        output = dispatcher.dispatch("get_screen_full", {"name": "HomeScreen"}, "myapp")
        assert "flex" in output

    def test_renders_hover_state_styles(self, dispatcher):
        output = dispatcher.dispatch("get_screen_full", {"name": "HomeScreen"}, "myapp")
        assert "hover" in output
        assert "#f0f0f0" in output

    def test_renders_props_table_with_prop_names(self, dispatcher):
        output = dispatcher.dispatch("get_screen_full", {"name": "HomeScreen"}, "myapp")
        assert "title"   in output
        assert "variant" in output

    def test_renders_required_prop_marker(self, dispatcher):
        output = dispatcher.dispatch("get_screen_full", {"name": "HomeScreen"}, "myapp")
        assert "✓" in output

    def test_renders_optional_prop_default_value(self, dispatcher):
        output = dispatcher.dispatch("get_screen_full", {"name": "HomeScreen"}, "myapp")
        assert "default" in output

    def test_renders_component_interactions(self, dispatcher):
        output = dispatcher.dispatch("get_screen_full", {"name": "HomeScreen"}, "myapp")
        assert "backgroundColor" in output

    def test_renders_component_tokens(self, dispatcher):
        output = dispatcher.dispatch("get_screen_full", {"name": "HomeScreen"}, "myapp")
        assert "primary" in output or "#007bff" in output

    def test_renders_component_children(self, dispatcher):
        output = dispatcher.dispatch("get_screen_full", {"name": "HomeScreen"}, "myapp")
        assert "Badge" in output

    def test_renders_component_jsx_snippet(self, dispatcher):
        output = dispatcher.dispatch("get_screen_full", {"name": "HomeScreen"}, "myapp")
        assert "<nav>" in output or "nav" in output


# ── Rendered output — layout profiles ────────────────────────────────────────

class TestGetScreenFullToolLayoutOutput:
    def test_renders_layout_section_heading(self, dispatcher):
        output = dispatcher.dispatch("get_screen_full", {"name": "HomeScreen"}, "myapp")
        assert "Layout" in output

    def test_renders_layout_display_value(self, dispatcher):
        output = dispatcher.dispatch("get_screen_full", {"name": "HomeScreen"}, "myapp")
        assert "flex" in output

    def test_renders_layout_width(self, dispatcher):
        output = dispatcher.dispatch("get_screen_full", {"name": "HomeScreen"}, "myapp")
        assert "100%" in output
