"""Tests for mcp_server.py — pick_conn, set_prototype, expand_query, handle protocol."""
import pytest
import mcp_server
from mcp_server import (
    pick_conn,
    tool_set_prototype,
    expand_query,
    handle,
    GRAPH_DIR,
)
from tests.conftest import make_conns


# ─────────────────────────────────────────────────────────────────────────────
# pick_conn — connection resolution
# ─────────────────────────────────────────────────────────────────────────────

class TestPickConn:
    def test_no_conns_returns_error(self):
        conn, err = pick_conn([])
        assert conn is None
        assert "No graphs loaded" in err
        assert "design-graph" in err

    def test_single_conn_auto_selects(self):
        conns = make_conns("myapp")
        conn, err = pick_conn(conns)
        assert conn == "conn:myapp"
        assert err is None

    def test_multiple_no_selection_returns_error(self):
        conns = make_conns("app1", "app2")
        conn, err = pick_conn(conns)
        assert conn is None
        assert "Multiple prototypes" in err
        assert "set_prototype" in err

    def test_explicit_doc_exact_match(self):
        conns = make_conns("app1", "app2")
        conn, err = pick_conn(conns, doc="app2")
        assert conn == "conn:app2"
        assert err is None

    def test_explicit_doc_substring_match(self):
        conns = make_conns("ipede-v7", "admin-panel")
        conn, err = pick_conn(conns, doc="admin")
        assert conn == "conn:admin-panel"
        assert err is None

    def test_explicit_doc_not_found(self):
        conns = make_conns("myapp")
        conn, err = pick_conn(conns, doc="nonexistent")
        assert conn is None
        assert "nonexistent" in err
        assert "myapp" in err

    def test_exact_match_beats_substring(self):
        conns = make_conns("app", "myapp")
        conn, err = pick_conn(conns, doc="app")
        assert conn == "conn:app"

    def test_active_prototype_used_when_no_doc(self):
        conns = make_conns("app1", "app2")
        mcp_server.ACTIVE_PROTOTYPE = "app2"
        conn, err = pick_conn(conns)
        assert conn == "conn:app2"
        assert err is None

    def test_active_prototype_not_found_returns_error(self):
        conns = make_conns("app1")
        mcp_server.ACTIVE_PROTOTYPE = "missing"
        conn, err = pick_conn(conns)
        assert conn is None
        assert "missing" in err
        assert "app1" in err

    def test_explicit_doc_overrides_active_prototype(self):
        conns = make_conns("app1", "app2")
        mcp_server.ACTIVE_PROTOTYPE = "app2"
        conn, err = pick_conn(conns, doc="app1")
        assert conn == "conn:app1"
        assert err is None

    def test_case_insensitive_match(self):
        conns = make_conns("MyApp")
        conn, err = pick_conn(conns, doc="myapp")
        assert conn == "conn:MyApp"


# ─────────────────────────────────────────────────────────────────────────────
# tool_set_prototype
# ─────────────────────────────────────────────────────────────────────────────

class TestSetPrototype:
    def test_sets_active_prototype(self):
        conns = make_conns("myapp")
        tool_set_prototype(conns, "myapp")
        assert mcp_server.ACTIVE_PROTOTYPE == "myapp"

    def test_returns_confirmation_message(self):
        conns = make_conns("myapp")
        result = tool_set_prototype(conns, "myapp")
        assert "myapp" in result
        assert "Active prototype" in result or "set to" in result

    def test_not_found_returns_error(self):
        conns = make_conns("myapp")
        result = tool_set_prototype(conns, "nonexistent")
        assert "not found" in result.lower()
        assert "myapp" in result
        assert mcp_server.ACTIVE_PROTOTYPE == ""

    def test_no_name_shows_active(self):
        conns = make_conns("myapp", "admin")
        mcp_server.ACTIVE_PROTOTYPE = "myapp"
        result = tool_set_prototype(conns, "")
        assert "myapp" in result

    def test_no_name_single_proto_shows_auto(self):
        conns = make_conns("myapp")
        result = tool_set_prototype(conns, "")
        assert "myapp" in result

    def test_no_name_no_active_lists_available(self):
        conns = make_conns("app1", "app2")
        result = tool_set_prototype(conns, "")
        assert "app1" in result
        assert "app2" in result

    def test_substring_match_resolves_full_name(self):
        conns = make_conns("ipede-v7")
        tool_set_prototype(conns, "ipede")
        assert mcp_server.ACTIVE_PROTOTYPE == "ipede-v7"


# ─────────────────────────────────────────────────────────────────────────────
# expand_query — PT/EN alias expansion
# ─────────────────────────────────────────────────────────────────────────────

class TestExpandQuery:
    def test_portuguese_button_alias(self):
        terms = expand_query("botão")
        assert "botão" in terms
        assert any("btn" in t.lower() or "button" in t.lower() for t in terms)

    def test_portuguese_modal_alias(self):
        terms = expand_query("modal")
        assert any("dialog" in t.lower() for t in terms)

    def test_no_alias_returns_lowercase_query(self):
        terms = expand_query("RestaurantCard")
        assert "restaurantcard" in terms

    def test_no_duplicates(self):
        terms = expand_query("botão")
        assert len(terms) == len(set(terms))

    def test_mixed_case_input_normalized(self):
        terms = expand_query("MODAL")
        assert all(t == t.lower() for t in terms)

    def test_multiple_aliases_in_query(self):
        terms = expand_query("botão modal")
        assert len(terms) > 2


# ─────────────────────────────────────────────────────────────────────────────
# handle() — MCP protocol layer
# ─────────────────────────────────────────────────────────────────────────────

def make_request(method, params=None, id=1):
    return {"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}}


class TestHandleInitialize:
    def test_no_graphs_degraded_mode(self):
        resp = handle([], make_request("initialize"))
        desc = resp["result"]["serverInfo"]["description"]
        assert "No graphs" in desc
        assert "design-graph" in desc

    def test_single_proto_auto_selected_in_description(self):
        conns = make_conns("myapp")
        resp = handle(conns, make_request("initialize"))
        desc = resp["result"]["serverInfo"]["description"]
        assert "myapp" in desc
        assert "auto" in desc.lower() or "active" in desc.lower()

    def test_multiple_protos_instructs_set_prototype(self):
        conns = make_conns("app1", "app2")
        resp = handle(conns, make_request("initialize"))
        desc = resp["result"]["serverInfo"]["description"]
        assert "set_prototype" in desc or "select" in desc.lower()

    def test_active_prototype_shown_in_description(self):
        conns = make_conns("app1", "app2")
        mcp_server.ACTIVE_PROTOTYPE = "app1"
        resp = handle(conns, make_request("initialize"))
        desc = resp["result"]["serverInfo"]["description"]
        assert "app1" in desc

    def test_returns_protocol_version(self):
        resp = handle([], make_request("initialize"))
        assert resp["result"]["protocolVersion"] == "2024-11-05"

    def test_version_field_present(self):
        resp = handle([], make_request("initialize"))
        assert "version" in resp["result"]["serverInfo"]


class TestHandleToolsList:
    def test_returns_all_tools(self):
        resp = handle([], make_request("tools/list"))
        names = {t["name"] for t in resp["result"]["tools"]}
        assert "list_screens" in names
        assert "get_component" in names
        assert "get_screen" in names
        assert "search" in names
        assert "impact" in names
        assert "set_prototype" in names

    def test_set_prototype_name_not_required(self):
        resp = handle([], make_request("tools/list"))
        sp = next(t for t in resp["result"]["tools"] if t["name"] == "set_prototype")
        assert "name" not in sp["inputSchema"].get("required", [])


class TestHandleToolsCall:
    def test_set_prototype_handled_without_conn(self):
        conns = make_conns("myapp")
        resp = handle(conns, make_request("tools/call", {
            "name": "set_prototype", "arguments": {"name": "myapp"}
        }))
        text = resp["result"]["content"][0]["text"]
        assert "myapp" in text

    def test_no_graphs_returns_setup_message(self):
        resp = handle([], make_request("tools/call", {
            "name": "get_component", "arguments": {"name": "Btn"}
        }))
        text = resp["result"]["content"][0]["text"]
        assert "No graphs" in text

    def test_multiple_protos_no_selection_returns_guidance(self):
        conns = make_conns("app1", "app2")
        resp = handle(conns, make_request("tools/call", {
            "name": "get_component", "arguments": {"name": "Btn"}
        }))
        text = resp["result"]["content"][0]["text"]
        assert "Multiple" in text or "set_prototype" in text

    def test_unknown_tool_returns_error_message(self):
        conns = make_conns("myapp")
        mcp_server.ACTIVE_PROTOTYPE = "myapp"
        resp = handle(conns, make_request("tools/call", {
            "name": "nonexistent_tool", "arguments": {}
        }))
        text = resp["result"]["content"][0]["text"]
        assert "Unknown" in text or "unknown" in text.lower()

    def test_initialized_notification_returns_none(self):
        resp = handle([], make_request("notifications/initialized"))
        assert resp is None

    def test_unknown_method_returns_error(self):
        resp = handle([], make_request("foo/bar"))
        assert "error" in resp
        assert resp["error"]["code"] == -32601
