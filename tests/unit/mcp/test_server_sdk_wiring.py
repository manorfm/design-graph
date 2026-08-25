"""
Tests for the mcp SDK wiring boundary: _to_sdk_tool, _AGENT_INSTRUCTIONS and
_build_sdk_server.

Context: the same design-graph server is commonly reached from several
projects at once (Cursor, Kiro and similar tools keep one MCP connection
shared across all open workspaces), and most requests in a session have
nothing to do with a prototype at all. _AGENT_INSTRUCTIONS is the MCP
protocol's own mechanism for teaching every connecting agent that judgment
call once, at the handshake — instead of the user repeating it in every
prompt or a per-project config file pinning one fixed prototype that may
not even be the relevant one for a given request.
"""

from __future__ import annotations

from design_graph.mcp.server import MCPServer, _AGENT_INSTRUCTIONS, _build_sdk_server, _to_sdk_tool


class _StubReader:
    def list_screens(self):
        return [{"name": "HomeScreen", "component_count": 1, "sections_count": 0, "top_components": []}]


class TestToSdkTool:
    def test_maps_name_description_and_schema(self):
        definition = {
            "name": "get_component",
            "description": "Return a component's implementation.",
            "inputSchema": {"type": "object", "properties": {}},
        }
        tool = _to_sdk_tool(definition)
        assert tool.name == "get_component"
        assert tool.description == "Return a component's implementation."
        assert tool.input_schema == {"type": "object", "properties": {}}

    def test_marks_every_tool_read_only(self):
        """Every design-graph tool only reads the graph — clients that
        respect annotations can treat calls as side-effect-free."""
        definition = {"name": "x", "description": "d", "inputSchema": {"type": "object"}}
        tool = _to_sdk_tool(definition)
        assert tool.annotations.read_only_hint is True


class TestAgentInstructions:
    def test_is_conditioned_on_the_task_involving_ui_work(self):
        """Most requests aren't about a prototype — the instructions must
        say so, not push every agent to check on every turn."""
        text = _AGENT_INSTRUCTIONS.lower()
        assert "component" in text or "page" in text or "screen" in text
        assert "prototype" in text

    def test_covers_selecting_among_multiple_prototypes(self):
        assert "set_prototype" in _AGENT_INSTRUCTIONS

    def test_covers_component_subtree_reconstruction(self):
        assert "get_component_full" in _AGENT_INSTRUCTIONS

    def test_covers_token_reuse_before_literal_values(self):
        assert "get_tokens" in _AGENT_INSTRUCTIONS


class TestBuildSdkServer:
    def _server(self):
        return MCPServer([("myapp", _StubReader())])

    def test_instructions_are_passed_through(self):
        sdk_server = _build_sdk_server(self._server())
        assert sdk_server.instructions == _AGENT_INSTRUCTIONS

    def test_name_is_design_graph(self):
        sdk_server = _build_sdk_server(self._server())
        assert sdk_server.name == "design-graph"

    def test_description_reflects_loaded_prototypes(self):
        sdk_server = _build_sdk_server(self._server())
        assert "myapp" in sdk_server.server_info.description
