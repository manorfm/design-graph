# T15 — MCPTools + MCPServer

**Fase**: 5 — MCP
**Arquivos**: `src/design_graph/mcp/tools.py`, `src/design_graph/mcp/server.py`
**Depende de**: T11 (GraphReader), T14 (MCPSearch)
**Bloqueia**: nada (último da Fase 5)

---

## Contrato: `tools.py`

```python
class ToolDispatcher:
    def __init__(self, readers: list[tuple[str, GraphReader]]):
        self._readers = readers
        self._search = Search(readers)  # instância de search.py

    def pick_reader(
        self, doc: str | None, active_doc: str
    ) -> tuple[GraphReader | None, str | None]:
        """
        Resolution: doc= → active_doc → auto-select se 1 → error.
        Retorna (reader, None) no sucesso, (None, error_msg) no erro.
        """

    def dispatch(self, tool_name: str, args: dict, active_doc: str) -> str:
        """Resolve reader e despacha para o método correto."""

    # Tools (todas retornam str formatado em Markdown)
    def list_screens(self) -> str: ...
    def get_screen(self, reader: GraphReader, name: str) -> str: ...
    def get_section(self, reader: GraphReader, screen: str, section: str) -> str: ...
    def get_component(self, reader: GraphReader, name: str) -> str: ...
    def get_tokens(self, reader: GraphReader, category: str | None) -> str: ...
    def find_token_usage(self, reader: GraphReader, value: str) -> str: ...
    def search(self, query: str) -> str: ...
    def impact(self, reader: GraphReader, name: str) -> str: ...
    def get_full_jsx(self, reader: GraphReader, name: str) -> str: ...
    def get_component_interactions(self, reader: GraphReader, name: str) -> str: ...
    def get_component_children(self, reader: GraphReader, name: str) -> str: ...  # NOVO

TOOL_DEFINITIONS: list[dict]  # schema MCP completo
```

---

## Contrato: `server.py`

```python
class MCPServer:
    def __init__(self, readers: list[tuple[str, GraphReader]]):
        self._dispatcher = ToolDispatcher(readers)
        self._active_doc: str = os.environ.get("DESIGN_GRAPH_DOC", "").strip()

    def run(self) -> None:
        """Loop principal: lê stdin, processa, escreve stdout."""

    def handle(self, msg: dict) -> dict | None:
        """Despacha 1 mensagem. Retorna None para notifications."""

def main() -> None:
    """Entry point: abre DBs, inicia MCPServer.run()."""
```

---

## TDD

```python
# tests/unit/mcp/test_tools.py

class TestPickReader:
    @pytest.fixture
    def dispatcher(self):
        return ToolDispatcher([("doc1", MockReader()), ("doc2", MockReader())])

    def test_explicit_doc_wins(self, dispatcher):
        reader, err = dispatcher.pick_reader(doc="doc1", active_doc="doc2")
        assert reader is not None
        assert err is None

    def test_active_doc_used_when_no_explicit(self, dispatcher):
        reader, err = dispatcher.pick_reader(doc=None, active_doc="doc2")
        assert reader is not None
        assert err is None

    def test_auto_select_single_reader(self):
        d = ToolDispatcher([("only", MockReader())])
        reader, err = d.pick_reader(doc=None, active_doc="")
        assert reader is not None
        assert err is None

    def test_error_multiple_no_selection(self, dispatcher):
        reader, err = dispatcher.pick_reader(doc=None, active_doc="")
        assert reader is None
        assert "Available" in err or "Call set_prototype" in err

    def test_error_unknown_doc(self, dispatcher):
        reader, err = dispatcher.pick_reader(doc="unknown", active_doc="")
        assert reader is None
        assert "unknown" in err.lower() or "not found" in err.lower()


class TestDispatch:
    @pytest.fixture
    def dispatcher(self):
        return ToolDispatcher([("doc1", MockReader())])

    def test_list_screens_returns_markdown(self, dispatcher):
        result = dispatcher.dispatch("list_screens", {}, "doc1")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_unknown_tool_returns_error_string(self, dispatcher):
        result = dispatcher.dispatch("unknown_tool", {}, "doc1")
        assert "unknown" in result.lower() or "not found" in result.lower()

    def test_get_component_children_available(self, dispatcher):
        result = dispatcher.dispatch(
            "get_component_children", {"name": "BtnPrimary"}, "doc1"
        )
        assert isinstance(result, str)


class TestToolDefinitions:
    def test_all_expected_tools_defined(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        expected = {
            "list_screens", "get_screen", "get_section", "get_component",
            "get_tokens", "find_token_usage", "search", "impact",
            "get_full_jsx", "get_component_interactions",
            "get_component_children",  # nova tool
            "set_prototype",
        }
        assert expected.issubset(names)

    def test_each_tool_has_description(self):
        for t in TOOL_DEFINITIONS:
            assert len(t.get("description", "")) > 20

    def test_each_tool_has_input_schema(self):
        for t in TOOL_DEFINITIONS:
            assert "inputSchema" in t
            assert t["inputSchema"]["type"] == "object"


# tests/unit/mcp/test_server.py

class TestMCPServer:
    def test_initialize_returns_protocol_version(self):
        server = MCPServer([("doc", MockReader())])
        response = server.handle({
            "jsonrpc": "2.0", "id": 1,
            "method": "initialize", "params": {}
        })
        assert response["result"]["protocolVersion"] == "2024-11-05"

    def test_tools_list_includes_new_tool(self):
        server = MCPServer([("doc", MockReader())])
        response = server.handle({
            "jsonrpc": "2.0", "id": 2,
            "method": "tools/list", "params": {}
        })
        names = [t["name"] for t in response["result"]["tools"]]
        assert "get_component_children" in names

    def test_tools_call_dispatched_correctly(self):
        server = MCPServer([("doc", MockReader())])
        response = server.handle({
            "jsonrpc": "2.0", "id": 3,
            "method": "tools/call",
            "params": {"name": "list_screens", "arguments": {}}
        })
        assert response["result"]["content"][0]["type"] == "text"

    def test_unknown_method_returns_error(self):
        server = MCPServer([])
        response = server.handle({
            "jsonrpc": "2.0", "id": 4,
            "method": "nonexistent", "params": {}
        })
        assert response["error"]["code"] == -32601

    def test_notification_returns_none(self):
        server = MCPServer([])
        result = server.handle({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {}
        })
        assert result is None

    def test_set_prototype_updates_active_doc(self):
        server = MCPServer([("myapp", MockReader())])
        server.handle({
            "jsonrpc": "2.0", "id": 5,
            "method": "tools/call",
            "params": {
                "name": "set_prototype",
                "arguments": {"name": "myapp"}
            }
        })
        assert server._active_doc == "myapp"
```

---

## Done when

- [x] Todos os testes passam
- [x] `TOOL_DEFINITIONS` inclui `get_component_children`
- [x] `server.py` não contém lógica de formatação de Markdown — delega para `tools.py`
- [x] Teste de integração E2E passa: `design-mcp` pode responder `list_screens` com grafo real
