# Plan 04 — Fase 5: MCP

## Objetivo

Separar o servidor MCP em 4 módulos com responsabilidades claras.
Adicionar busca com scoring, nova tool `get_component_children` e
isolar os aliases em arquivo próprio.

## Pré-requisito

Fase 3 completa: `GraphReader` disponível.

## Entregáveis

```
src/design_graph/mcp/
  __init__.py
  aliases.py
  search.py
  tools.py
  server.py
```

## Sequência TDD

### 5.1 `aliases.py`

```python
class TestAliases:
    def test_get_aliases_returns_dict(self):
        aliases = get_aliases()
        assert isinstance(aliases, dict)

    def test_botao_maps_to_button_variants(self):
        aliases = get_aliases()
        assert "Btn" in aliases.get("botão", []) or "Button" in aliases.get("botão", [])

    def test_returned_dict_is_copy(self):
        a = get_aliases()
        b = get_aliases()
        a["test_key"] = []
        assert "test_key" not in b  # modificar a cópia não afeta a original
```

### 5.2 `search.py`

```python
class TestSearch:
    def test_exact_match_scores_100(self):
        assert _score("SectionCard", "SectionCard") == 100

    def test_prefix_match_scores_80(self):
        assert _score("SectionCard", "Section") == 80

    def test_suffix_match_scores_60(self):
        assert _score("SectionCard", "Card") == 60

    def test_contains_match_scores_40(self):
        assert _score("RestaurantSectionCard", "tionCard") == 40

    def test_no_match_scores_0(self):
        assert _score("BtnPrimary", "Modal") == 0

    def test_expand_query_applies_aliases(self):
        terms = _expand_query("botão", get_aliases())
        assert any(t in ["btn", "button"] for t in terms)

    def test_expand_query_deduplicates(self):
        terms = _expand_query("card card", get_aliases())
        assert terms.count("card") == 1

    def test_search_returns_sorted_by_score(self, mock_readers):
        results = search(mock_readers, "card")
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_search_deduplicates_by_doc_and_id(self, mock_readers):
        # Mesmo componente não aparece duas vezes no mesmo doc
        results = search(mock_readers, "SectionCard")
        ids = [(r.doc, r.id) for r in results]
        assert len(ids) == len(set(ids))
```

### 5.3 `tools.py`

```python
class TestToolDispatcher:
    def test_pick_reader_explicit_doc(self, mock_readers):
        dispatcher = ToolDispatcher(mock_readers)
        reader, err = dispatcher.pick_reader(doc="myapp", active_doc="")
        assert reader is not None
        assert err is None

    def test_pick_reader_active_doc(self, mock_readers):
        dispatcher = ToolDispatcher(mock_readers)
        reader, err = dispatcher.pick_reader(doc=None, active_doc="myapp")
        assert reader is not None

    def test_pick_reader_auto_select_single(self):
        single = [("only", MockReader())]
        dispatcher = ToolDispatcher(single)
        reader, err = dispatcher.pick_reader(doc=None, active_doc="")
        assert reader is not None
        assert err is None

    def test_pick_reader_error_multiple_no_selection(self, mock_readers):
        dispatcher = ToolDispatcher(mock_readers)  # 2+ readers
        reader, err = dispatcher.pick_reader(doc=None, active_doc="")
        assert reader is None
        assert err is not None  # mensagem de erro legível

    def test_get_component_children_uses_reader(self, mock_reader):
        mock_reader.get_component_children.return_value = ["Badge", "Icon"]
        dispatcher = ToolDispatcher([("doc", mock_reader)])
        result = dispatcher.get_component_children(mock_reader, "BtnPrimary")
        assert "Badge" in result
        assert "Icon" in result
```

### 5.4 `server.py`

```python
class TestMCPServer:
    def test_initialize_response(self):
        server = MCPServer([("doc", MockReader())])
        response = server.handle({"method": "initialize", "id": 1, "params": {}})
        assert response["result"]["protocolVersion"] == "2024-11-05"
        assert "tools" in response["result"]["capabilities"]

    def test_tools_list_response(self):
        server = MCPServer([("doc", MockReader())])
        response = server.handle({"method": "tools/list", "id": 2, "params": {}})
        tool_names = [t["name"] for t in response["result"]["tools"]]
        assert "get_component_children" in tool_names  # nova tool

    def test_unknown_method_returns_error(self):
        server = MCPServer([])
        response = server.handle({"method": "unknown", "id": 3, "params": {}})
        assert response["error"]["code"] == -32601

    def test_set_prototype_updates_active_doc(self):
        server = MCPServer([("myapp", MockReader())])
        server.handle({
            "method": "tools/call",
            "id": 4,
            "params": {"name": "set_prototype", "arguments": {"name": "myapp"}}
        })
        assert server._active_doc == "myapp"
```

## Mock de readers para testes unitários

```python
# tests/conftest.py

class MockReader:
    """Reader falso para testes de MCP sem banco real."""
    def list_screens(self): return [{"name": "TestScreen", "component_count": 2}]
    def get_component(self, name): return {"name": name, "comp_type": "card"}
    def get_component_children(self, name): return []
    # ... outros métodos retornam dados mínimos
```

## Critério de aceite

```bash
pytest tests/unit/mcp/ -v
pytest tests/integration/test_mcp_e2e.py -v
# search retorna resultados em ordem de score
# get_component_children funciona end-to-end
# pick_reader resolve corretamente nos 4 cenários
```

## Guardrails desta fase

1. `server.py` não importa `kuzu` diretamente — usa apenas `GraphReader`
2. `tools.py` não acessa `sys.stdin`/`sys.stdout` — recebe dados e retorna strings
3. `aliases.py` não importa de nenhum outro módulo do projeto
4. `search.py` não modifica os readers — read-only
5. `_active_doc` só é modificado em `server.py` — tools.py não tem acesso a ele
