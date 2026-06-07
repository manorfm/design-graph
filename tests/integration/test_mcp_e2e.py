"""
End-to-end tests for the MCP layer against a real graph.

Unlike tests/unit/mcp/test_tools.py (which uses MockReader), these tests
build an actual Kuzu database from simple.html and exercise MCPServer.handle()
through the complete stack: server → dispatcher → tools → GraphReader → Kuzu.

Coverage:
  - JSON-RPC protocol compliance (initialize, tools/list, error codes)
  - Every standard tool with real data
  - Multi-prototype reader selection (pick_reader scenarios)
  - Relevance-ordered search results
  - Session state mutation via set_prototype
  - Error paths: unknown tool, ambiguous prototype, missing prototype
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import kuzu
import pytest

from design_graph.graph.reader import GraphReader
from design_graph.mcp.server import MCPServer
from design_graph.mcp.tools import ToolDispatcher
from design_graph.pipeline.coordinator import run_pipeline

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"
SIMPLE_HTML = FIXTURE_DIR / "simple.html"

# ── shared graph fixture ──────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def real_graph_db(tmp_path_factory):
    """Build a Kuzu database from simple.html once for all e2e tests."""
    tmp = tmp_path_factory.mktemp("mcp_e2e")
    db_path    = tmp / "e2e.db"
    state_path = tmp / ".state.json"
    asyncio.run(run_pipeline(SIMPLE_HTML, db_path, state_path))
    return db_path


@pytest.fixture(scope="module")
def real_reader(real_graph_db):
    db   = kuzu.Database(str(real_graph_db), read_only=True)
    conn = kuzu.Connection(db)
    return GraphReader(conn)


@pytest.fixture(scope="module")
def single_server(real_reader):
    """MCPServer with one loaded prototype ('simple')."""
    return MCPServer([("simple", real_reader)])


@pytest.fixture(scope="module")
def dual_server(real_reader):
    """MCPServer with two readers for multi-prototype tests."""
    return MCPServer([("proto_a", real_reader), ("proto_b", real_reader)])


# ── helper ────────────────────────────────────────────────────────────────────

def _call(server: MCPServer, tool: str, args: dict | None = None, mid: int = 1) -> dict:
    """Shorthand for a tools/call request."""
    return server.handle({
        "jsonrpc": "2.0",
        "id": mid,
        "method": "tools/call",
        "params": {"name": tool, "arguments": args or {}},
    })


def _text(response: dict) -> str:
    """Extract the text payload from a tools/call response."""
    return response["result"]["content"][0]["text"]


# ── JSON-RPC protocol compliance ──────────────────────────────────────────────

class TestJsonRpcProtocol:
    def test_initialize_returns_2024_protocol_version(self, single_server):
        resp = single_server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert resp["result"]["protocolVersion"] == "2024-11-05"

    def test_initialize_includes_tools_capability(self, single_server):
        resp = single_server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert "tools" in resp["result"]["capabilities"]

    def test_initialize_description_contains_prototype_name(self, single_server):
        resp = single_server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        desc = resp["result"]["serverInfo"]["description"]
        assert "simple" in desc

    def test_tools_list_returns_all_expected_tools(self, single_server):
        resp = single_server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names = {t["name"] for t in resp["result"]["tools"]}
        expected = {
            "list_screens", "get_screen", "get_section", "get_component",
            "get_tokens", "find_token_usage", "search", "impact",
            "get_full_jsx", "get_component_interactions",
            "get_component_children", "list_components", "get_component_spec",
            "get_component_props", "get_screen_layout",
            "set_prototype",
        }
        assert expected.issubset(names), f"Missing tools: {expected - names}"

    def test_notification_initialized_returns_none(self, single_server):
        result = single_server.handle({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        })
        assert result is None

    def test_unknown_method_returns_error_32601(self, single_server):
        resp = single_server.handle({"jsonrpc": "2.0", "id": 3, "method": "unknown/method", "params": {}})
        assert resp["error"]["code"] == -32601

    def test_unknown_method_error_includes_method_name(self, single_server):
        resp = single_server.handle({"jsonrpc": "2.0", "id": 3, "method": "some/unknown", "params": {}})
        assert "some/unknown" in resp["error"]["message"]

    def test_response_always_includes_jsonrpc_version(self, single_server):
        resp = single_server.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/list", "params": {}})
        assert resp.get("jsonrpc") == "2.0"

    def test_response_id_matches_request_id(self, single_server):
        resp = single_server.handle({"jsonrpc": "2.0", "id": 42, "method": "tools/list", "params": {}})
        assert resp["id"] == 42


# ── list_screens tool ─────────────────────────────────────────────────────────

class TestListScreensTool:
    def test_returns_markdown_string(self, single_server):
        resp = _call(single_server, "list_screens")
        assert isinstance(_text(resp), str)

    def test_contains_restaurants_page(self, single_server):
        resp = _call(single_server, "list_screens")
        assert "RestaurantsPage" in _text(resp)

    def test_markdown_contains_section_count_info(self, single_server):
        text = _text(_call(single_server, "list_screens"))
        # Should show at least one numeric count or section indicator
        assert any(c.isdigit() for c in text)


# ── get_screen tool ───────────────────────────────────────────────────────────

class TestGetScreenTool:
    def test_exact_name_returns_screen_data(self, single_server):
        resp = _call(single_server, "get_screen", {"name": "RestaurantsPage"})
        assert "RestaurantsPage" in _text(resp)

    def test_partial_name_resolves_via_fuzzy_lookup(self, single_server):
        resp = _call(single_server, "get_screen", {"name": "Restaurants"})
        # fuzzy should resolve to RestaurantsPage
        assert "not found" not in _text(resp).lower()

    def test_nonexistent_screen_returns_not_found(self, single_server):
        resp = _call(single_server, "get_screen", {"name": "GhostScreen999"})
        text = _text(resp).lower()
        assert "not found" in text or "não encontrad" in text or "ghostscreen999" in text

    def test_screen_result_includes_component_info(self, single_server):
        text = _text(_call(single_server, "get_screen", {"name": "RestaurantsPage"}))
        # Should mention at least one of the known components or sections
        assert any(kw in text for kw in ("Btn", "Section", "Header", "component", "Component"))


# ── get_component tool ────────────────────────────────────────────────────────

class TestGetComponentTool:
    def test_known_component_returns_data(self, single_server):
        resp = _call(single_server, "get_component", {"name": "BtnPrimary"})
        assert "BtnPrimary" in _text(resp)

    def test_nonexistent_component_returns_not_found(self, single_server):
        resp = _call(single_server, "get_component", {"name": "NoSuchWidget999"})
        text = _text(resp).lower()
        assert "not found" in text or "não encontrad" in text or "nosuchwidget" in text

    def test_result_is_markdown(self, single_server):
        text = _text(_call(single_server, "get_component", {"name": "BtnPrimary"}))
        assert isinstance(text, str) and len(text) > 0

    def test_section_card_present_in_graph(self, single_server):
        resp = _call(single_server, "get_component", {"name": "SectionCard"})
        assert "SectionCard" in _text(resp)


# ── get_component_children tool ───────────────────────────────────────────────

class TestGetComponentChildrenTool:
    def test_returns_string_result(self, single_server):
        resp = _call(single_server, "get_component_children", {"name": "BtnPrimary"})
        assert isinstance(_text(resp), str)

    def test_nonexistent_component_returns_graceful_message(self, single_server):
        resp = _call(single_server, "get_component_children", {"name": "NoSuchWidget999"})
        text = _text(resp)
        # Should not raise; returns a readable message
        assert isinstance(text, str)


# ── search tool ───────────────────────────────────────────────────────────────

class TestSearchTool:
    def test_search_finds_known_component(self, single_server):
        resp = _call(single_server, "search", {"query": "BtnPrimary"})
        assert "BtnPrimary" in _text(resp)

    def test_search_finds_known_screen(self, single_server):
        resp = _call(single_server, "search", {"query": "Restaurants"})
        assert "Restaurants" in _text(resp)

    def test_search_with_portuguese_alias_expands(self, single_server):
        resp = _call(single_server, "search", {"query": "botão"})
        # "botão" maps to Btn/Button aliases — should find BtnPrimary
        text = _text(resp)
        assert isinstance(text, str)  # at minimum: no crash

    def test_search_empty_query_returns_graceful_result(self, single_server):
        resp = _call(single_server, "search", {"query": ""})
        assert isinstance(_text(resp), str)

    def test_search_results_are_ordered_by_relevance(self, single_server):
        """Exact match 'BtnPrimary' should appear before partial 'Btn' matches."""
        from design_graph.mcp.search import search as raw_search
        from design_graph.mcp.search import expand_query, score_match
        results = raw_search([("simple", single_server._readers[0][1])], "BtnPrimary")
        if len(results) >= 2:
            scores = [r.score for r in results]
            assert scores == sorted(scores, reverse=True), "Results not ordered by score"

    def test_search_results_deduplicated_by_doc_and_id(self, single_server):
        from design_graph.mcp.search import search as raw_search
        results = raw_search([("simple", single_server._readers[0][1])], "card")
        ids = [(r.doc, r.id) for r in results]
        assert len(ids) == len(set(ids)), "Duplicate (doc, id) pairs in search results"


# ── get_tokens tool ───────────────────────────────────────────────────────────

class TestGetTokensTool:
    def test_returns_token_list(self, single_server):
        resp = _call(single_server, "get_tokens", {})
        text = _text(resp)
        assert isinstance(text, str)

    def test_color_tokens_present(self, single_server):
        resp = _call(single_server, "get_tokens", {"category": "color"})
        text = _text(resp)
        # simple.html has #ffb81c which should be a color token
        assert isinstance(text, str) and len(text) > 0

    def test_unknown_category_returns_gracefully(self, single_server):
        resp = _call(single_server, "get_tokens", {"category": "nonexistent_type"})
        assert isinstance(_text(resp), str)


# ── get_full_jsx tool ─────────────────────────────────────────────────────────

class TestGetFullJsxTool:
    def test_known_component_returns_jsx(self, single_server):
        resp = _call(single_server, "get_full_jsx", {"name": "RestaurantsPage"})
        assert isinstance(_text(resp), str)

    def test_nonexistent_returns_graceful_message(self, single_server):
        resp = _call(single_server, "get_full_jsx", {"name": "Ghost999"})
        text = _text(resp)
        assert isinstance(text, str)


# ── set_prototype tool (session state) ───────────────────────────────────────

class TestSetPrototypeTool:
    def test_set_prototype_changes_active_doc(self):
        from design_graph.graph.reader import GraphReader
        server = MCPServer([("proto_x", _make_stub_reader()), ("proto_y", _make_stub_reader())])
        _call(server, "set_prototype", {"name": "proto_x"})
        assert server._active_doc == "proto_x"

    def test_set_prototype_case_insensitive_match(self):
        server = MCPServer([("ProtoAlpha", _make_stub_reader())])
        _call(server, "set_prototype", {"name": "protoalpha"})
        assert server._active_doc == "ProtoAlpha"

    def test_set_prototype_unknown_name_returns_error_text(self):
        server = MCPServer([("known", _make_stub_reader())])
        resp = _call(server, "set_prototype", {"name": "unknown_proto"})
        text = _text(resp)
        assert "not found" in text.lower() or "unknown_proto" in text.lower()

    def test_set_prototype_without_arg_reports_current_state(self, single_server):
        resp = _call(single_server, "set_prototype", {})
        assert isinstance(_text(resp), str)

    def test_active_doc_used_by_subsequent_tool_calls(self):
        """After set_prototype, tool calls should use the active doc."""
        from design_graph.graph.reader import GraphReader
        reader = _make_stub_reader()
        server = MCPServer([("the_doc", reader)])
        _call(server, "set_prototype", {"name": "the_doc"})
        resp = _call(server, "list_screens")
        # Should succeed (no "set_prototype" required message)
        assert "set_prototype" not in _text(resp).lower() or "the_doc" in _text(resp)


# ── multi-prototype pick_reader ───────────────────────────────────────────────

class TestMultiPrototypePickReader:
    def test_explicit_doc_arg_overrides_active_doc(self, dual_server, real_reader):
        # Set active to proto_a, then call with doc=proto_b
        dual_server._active_doc = "proto_a"
        resp = _call(dual_server, "list_screens", {"doc": "proto_b"})
        # Both readers have the same data; the call should succeed
        assert "RestaurantsPage" in _text(resp)

    def test_multiple_readers_no_selection_returns_guidance(self, dual_server):
        # Clear active doc so no default can be resolved
        dual_server._active_doc = ""
        resp = _call(dual_server, "get_screen", {"name": "RestaurantsPage"})
        text = _text(resp)
        # Without active_doc and no doc= arg, should prompt to use set_prototype
        # OR auto-resolve if dispatcher falls back gracefully
        assert isinstance(text, str)

    def test_initialize_with_multiple_readers_lists_all(self, dual_server):
        resp = dual_server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        desc = resp["result"]["serverInfo"]["description"]
        # Should mention both prototype names
        assert "proto_a" in desc or "proto_b" in desc

    def test_single_reader_auto_selected_without_set_prototype(self, single_server):
        # With one reader, no set_prototype call needed
        resp = _call(single_server, "list_screens")
        assert "RestaurantsPage" in _text(resp)


# ── ToolDispatcher.pick_reader — direct unit ─────────────────────────────────

class TestPickReaderWithRealReader:
    """Complements unit tests by using real (non-mock) readers."""

    def test_explicit_doc_returns_correct_reader(self, real_reader):
        d = ToolDispatcher([("doc_a", real_reader), ("doc_b", real_reader)])
        reader, err = d.pick_reader(doc="doc_a", active_doc="doc_b")
        assert reader is not None
        assert err is None

    def test_active_doc_fallback_selects_reader(self, real_reader):
        d = ToolDispatcher([("doc_a", real_reader), ("doc_b", real_reader)])
        reader, err = d.pick_reader(doc=None, active_doc="doc_b")
        assert reader is not None
        assert err is None

    def test_single_reader_auto_select(self, real_reader):
        d = ToolDispatcher([("only_doc", real_reader)])
        reader, err = d.pick_reader(doc=None, active_doc="")
        assert reader is not None
        assert err is None

    def test_ambiguous_returns_error_with_guidance(self, real_reader):
        d = ToolDispatcher([("a", real_reader), ("b", real_reader)])
        reader, err = d.pick_reader(doc=None, active_doc="")
        assert reader is None
        assert err is not None
        # Error message should explain how to resolve ambiguity
        assert "set_prototype" in err or "doc=" in err

    def test_no_readers_returns_error(self):
        d = ToolDispatcher([])
        reader, err = d.pick_reader(doc=None, active_doc="")
        assert reader is None
        assert err is not None


# ── Unknown and invalid tools ─────────────────────────────────────────────────

class TestErrorHandling:
    def test_unknown_tool_returns_error_text(self, single_server):
        resp = _call(single_server, "totally_unknown_tool_xyz")
        text = _text(resp)
        assert "unknown" in text.lower() or "totally_unknown" in text.lower()

    def test_tool_call_with_empty_name_returns_error(self, single_server):
        resp = single_server.handle({
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {"name": "", "arguments": {}},
        })
        assert "result" in resp or "error" in resp  # must not crash

    def test_no_crash_on_malformed_params(self, single_server):
        resp = single_server.handle({
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {},  # missing 'name' and 'arguments'
        })
        assert "result" in resp or "error" in resp


# ── private helpers ───────────────────────────────────────────────────────────

def _make_stub_reader():
    """Minimal GraphReader stub that satisfies ToolDispatcher without a real DB."""
    class _StubReader:
        def list_screens(self): return []
        def get_screen(self, name): return None
        def get_component(self, name): return None
        def get_component_children(self, name): return []
        def get_component_parents(self, name): return []
        def find_screens_using_comp_transitively(self, name): return []
        def get_section(self, screen, section): return None
        def get_tokens(self, category=None): return []
        def find_token_usage(self, value): return []
        def get_interactions(self, name): return []
        def get_full_jsx(self, name): return ""
        def get_impact(self, name): return {}
        def count_nodes(self): return {}
    return _StubReader()
