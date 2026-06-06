# T18 — `list_components`: Reader + MCP Tool

**Change**: C08 — Component Discovery Tools
**Arquivos**:
  - `src/design_graph/graph/reader.py`
  - `src/design_graph/mcp/tools.py`
**Depende de**: T11 (GraphReader), T15 (MCPTools)
**Bloqueia**: T19 (usa mesma infraestrutura de testes)

---

## Contrato: Reader

```python
def list_components(self, comp_type: str | None = None) -> list[dict]:
    """
    Return all components sorted by occurrence desc.
    If comp_type is given, return only components of that type.
    Each dict: name, comp_type, occurrence.
    """
```

Tipos válidos: `button`, `card`, `modal`, `form`, `badge`, `toggle`, `chart`,
`navigation`, `list-item`, `screen`, `tab`, `component`.

---

## Contrato: MCP Tool

**Nome**: `list_components`

**Input schema**:
```json
{
  "type": "object",
  "properties": {
    "comp_type": {
      "type": "string",
      "description": "Tipo semântico: button|card|modal|form|badge|toggle|chart|navigation|list-item|screen|tab|component"
    },
    "doc": { "type": "string", "description": "Nome do protótipo" }
  },
  "required": []
}
```

**Saída (Markdown)**:
```
## Componentes (15 total)

| Nome | Tipo | Ocorrências |
|------|------|-------------|
| SectionCard | card | 12 |
| BtnPrimary | button | 8 |
| Badge | badge | 6 |
...
```

Quando filtrado: cabeçalho inclui `— tipo: button`.
Quando vazio: `Nenhum componente encontrado para o tipo "unknown".`

---

## TDD

```python
# tests/unit/graph/test_reader_advanced_queries.py

class TestListComponents:
    def test_all_components_without_filter(self, populated_reader):
        comps = populated_reader.list_components()
        names = {c["c.name"] for c in comps}
        assert {"BtnPrimary", "Badge", "SectionCard"}.issubset(names)

    def test_filter_by_comp_type_button(self, populated_reader):
        comps = populated_reader.list_components(comp_type="button")
        assert all(c["c.comp_type"] == "button" for c in comps)

    def test_filter_unknown_type_returns_empty(self, populated_reader):
        assert populated_reader.list_components(comp_type="xyz_invalid") == []

    def test_sorted_by_occurrence_desc(self, populated_reader):
        comps = populated_reader.list_components()
        occs = [c["c.occurrence"] for c in comps]
        assert occs == sorted(occs, reverse=True)

    def test_each_entry_has_name_type_occurrence(self, populated_reader):
        for c in populated_reader.list_components():
            assert "c.name" in c
            assert "c.comp_type" in c
            assert "c.occurrence" in c

# tests/unit/mcp/test_tools.py  (append to existing file)

class TestListComponentsTool:
    def test_tool_defined(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "list_components" in names

    def test_tool_has_description(self):
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "list_components")
        assert len(tool["description"]) > 20

    def test_dispatch_no_filter_returns_markdown(self, dispatcher):
        result = dispatcher.dispatch("list_components", {}, "doc1")
        assert isinstance(result, str)
        assert "|" in result  # tabela markdown

    def test_dispatch_with_type_filter(self, dispatcher):
        result = dispatcher.dispatch("list_components", {"comp_type": "button"}, "doc1")
        assert isinstance(result, str)
```

---

## Done when

- [ ] `list_components()` no reader passa todos os testes acima
- [ ] Tool `list_components` em `TOOL_DEFINITIONS` com description e inputSchema
- [ ] Handler em `tools.py` retorna Markdown com tabela
- [ ] `dispatch("list_components", {}, ...)` não lança exceção
- [ ] G3 guardrail: nenhum `CREATE`/`DELETE`/`MERGE` em `reader.py`
