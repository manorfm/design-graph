# T19 — `get_component_spec`: Reader + MCP Tool

**Change**: C08 — Component Discovery Tools
**Arquivos**:
  - `src/design_graph/graph/reader.py`
  - `src/design_graph/mcp/tools.py`
**Depende de**: T18 (list_components — mesmo arquivo)
**Bloqueia**: nada

---

## Contrato: Reader

```python
def get_component_spec(self, name: str) -> dict | None:
    """
    Return structured component spec for AI agent consumption.
    Uses fuzzy name resolution. Returns None if not found.

    Returned dict keys:
      c.name, c.comp_type, c.jsx_snippet, c.occurrence, c.classes,
      styles_by_state: dict[state → list[{property, value}]],
      tokens: list[{t.label, t.value, t.category}],
      texts: list[{t.content, t.text_type, t.element}],
      interactions: list[{i.trigger, i.css_prop, i.from_val, i.to_val, i.transition}],
      children: list[str],
      parents: list[str],
      screens_using: list[str],
    """
```

A diferença para `get_component()`:
- `styles` é agrupado por `state` em vez de lista plana
- Inclui `parents` (novo)
- `screens_using` usa a query transitiva corrigida (C07)
- Não retorna tokens no formato plano de `get_component` — idem, mas explicitamente agrupados

---

## Contrato: MCP Tool

**Nome**: `get_component_spec`

**Input schema**:
```json
{
  "type": "object",
  "properties": {
    "name": { "type": "string", "description": "Nome (parcial ou completo) do componente" },
    "doc":  { "type": "string", "description": "Nome do protótipo" }
  },
  "required": ["name"]
}
```

**Saída (Markdown)**:
```markdown
# Spec: BtnPrimary
**Tipo**: button | **Ocorrências**: 8

## Hierarquia
- Pais: SectionCard
- Filhos: Badge

## Telas
RestaurantsPage, LoginPage

## Estilos — default
| Propriedade | Valor |
|---|---|
| backgroundColor | #ffb81c |
| borderRadius | 8px |
| padding | 12px 24px |

## Estilos — hover
| Propriedade | Valor |
|---|---|
| backgroundColor | #e6a510 |

## Tokens
| Label | Valor | Categoria |
|---|---|---|
| primary | #ffb81c | color |
| radius_md | 8px | radius |

## Textos
- "Adicionar ao carrinho" (button)
- "Ver detalhes" (button)

## Interações
- hover: backgroundColor #ffb81c → #e6a510 (transition: all 0.2s)

## JSX
\`\`\`jsx
<button style={{ backgroundColor: '#ffb81c', ... }}>
  <Badge />
  {children}
</button>
\`\`\`
```

---

## TDD

```python
# tests/unit/graph/test_reader_advanced_queries.py

class TestGetComponentSpec:
    def test_returns_none_for_unknown(self, populated_reader):
        assert populated_reader.get_component_spec("NonExistent") is None

    def test_name_and_type_present(self, populated_reader):
        spec = populated_reader.get_component_spec("BtnPrimary")
        assert spec["c.name"] == "BtnPrimary"
        assert spec["c.comp_type"] == "button"

    def test_styles_grouped_by_state(self, populated_reader):
        spec = populated_reader.get_component_spec("BtnPrimary")
        assert "styles_by_state" in spec
        assert isinstance(spec["styles_by_state"], dict)

    def test_default_state_present_when_has_styles(self, populated_reader):
        spec = populated_reader.get_component_spec("BtnPrimary")
        if spec["styles_by_state"]:
            assert "default" in spec["styles_by_state"]

    def test_tokens_list(self, populated_reader):
        spec = populated_reader.get_component_spec("BtnPrimary")
        assert isinstance(spec["tokens"], list)

    def test_children_list(self, populated_reader):
        spec = populated_reader.get_component_spec("BtnPrimary")
        assert "Badge" in spec["children"]

    def test_parents_list(self, populated_reader):
        spec = populated_reader.get_component_spec("Badge")
        assert "BtnPrimary" in spec["parents"]

    def test_screens_using_list(self, populated_reader):
        spec = populated_reader.get_component_spec("BtnPrimary")
        assert isinstance(spec["screens_using"], list)

    def test_jsx_snippet_present(self, populated_reader):
        spec = populated_reader.get_component_spec("BtnPrimary")
        assert "c.jsx_snippet" in spec

    def test_fuzzy_resolution(self, populated_reader):
        spec = populated_reader.get_component_spec("btn")
        assert spec is not None

# tests/unit/mcp/test_tools.py

class TestGetComponentSpecTool:
    def test_tool_in_definitions(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "get_component_spec" in names

    def test_tool_requires_name(self):
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "get_component_spec")
        assert "name" in tool["inputSchema"]["required"]

    def test_dispatch_known_component(self, dispatcher):
        result = dispatcher.dispatch("get_component_spec", {"name": "BtnPrimary"}, "doc1")
        assert isinstance(result, str)
        assert "BtnPrimary" in result

    def test_dispatch_unknown_returns_not_found(self, dispatcher):
        result = dispatcher.dispatch("get_component_spec", {"name": "Xxxxxxx"}, "doc1")
        assert "not found" in result.lower() or "xxxxxxx" in result.lower()
```

---

## Done when

- [ ] `get_component_spec()` no reader retorna dict com todos os campos especificados
- [ ] `styles_by_state` é um `dict[str, list[dict]]` (agrupado por state)
- [ ] Fuzzy resolution funciona igual ao `get_component()`
- [ ] Tool `get_component_spec` em `TOOL_DEFINITIONS`
- [ ] Handler formata Markdown com seções Hierarquia, Estilos, Tokens, Textos, Interações, JSX
- [ ] G3 guardrail mantido em `reader.py`
