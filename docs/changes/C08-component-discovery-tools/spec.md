# Spec C08 — MCP: Tools de Descoberta de Componentes

## Problema

O MCP não tem ferramenta para:
1. Listar todos os componentes com filtro por tipo (`button`, `card`, `modal`, ...)
2. Obter a spec completa de um componente num formato estruturado para geração de UI

O agente hoje precisa fazer `search("Btn")` e adivinhar o que existe. Não consegue
perguntar "liste todos os cards" ou "dê-me a spec do BtnPrimary no formato que
preciso para codificar o componente".

---

## Solução: 2 novas tools

### Tool 1: `list_components`

Lista todos os componentes do grafo, com filtro opcional por tipo semântico.

**MCP input schema:**
```json
{
  "comp_type": "button",  // opcional: button|card|modal|form|badge|toggle|chart|navigation|list-item|screen|component
  "doc": "app"            // opcional: protótipo alvo
}
```

**Saída Markdown:**
```
## Componentes — tipo: button (3 encontrados)

| Nome | Tipo | Ocorrências | Filhos |
|------|------|-------------|--------|
| BtnPrimary | button | 8 | Badge |
| BtnSecondary | button | 4 | — |
| IconBtn | button | 2 | Icon |
```

**Reader method:**
```python
def list_components(self, comp_type: str | None = None) -> list[dict]:
    """
    Return all components, optionally filtered by comp_type.
    Each dict: name, comp_type, occurrence, children_count.
    Sorted by occurrence desc.
    """
```

### Tool 2: `get_component_spec`

Retorna a spec completa de um componente em formato otimizado para um agente de IA
que precisa construir ou reproduzir aquele componente.

**MCP input schema:**
```json
{
  "name": "BtnPrimary",
  "doc": "app"
}
```

**Saída Markdown:**
```
# Spec do Componente: BtnPrimary
**Tipo**: button | **Ocorrências**: 8 | **Telas**: RestaurantsPage, LoginPage

## Hierarquia
- Pai(s): SectionCard, CardWrapper
- Filho(s): Badge

## Estilos por estado
### default
| Propriedade | Valor | Token |
|-------------|-------|-------|
| backgroundColor | #ffb81c | primary |
| borderRadius | 8px | radius_md |
| padding | 12px 24px | spacing_12, spacing_24 |

### hover
| Propriedade | Valor | Token |
|-------------|-------|-------|
| backgroundColor | #e6a510 | — |

## Tokens utilizados
- `primary` (#ffb81c) — cor
- `radius_md` (8px) — radius

## Textos
- "Adicionar ao carrinho" (button)
- "Ver detalhes" (button)

## Interações
- hover: backgroundColor #ffb81c → #e6a510 (transition: all 0.2s)

## JSX (estrutura visual)
\`\`\`jsx
<button style={{ backgroundColor: '#ffb81c', borderRadius: '8px', ... }}>
  <Badge />
  {children}
</button>
\`\`\`
```

**Reader method:**
```python
def get_component_spec(self, name: str) -> dict | None:
    """
    Return structured component spec for AI agent consumption.
    Aggregates: component metadata, styles by state, tokens, texts,
    interactions, parent/child hierarchy, screens using it, jsx_snippet.
    Tokens are cross-referenced with styles where value matches.
    """
```

---

## Invariantes

- Ambas as tools são **read-only** (G3)
- `list_components` sem filtro retorna todos os componentes — não pagina (limite razoável: 200)
- `get_component_spec` usa fuzzy match igual ao `get_component` existente
- A saída de `get_component_spec` é mais rica que `get_component` — inclui cross-referência token↔estilo
- O nome da seção de estilos usa o `state` da tabela Style: "default", "hover", "focus"

## Tipos de `comp_type` válidos

Os mesmos inferidos em `extraction/component_extractor.py`:
`button`, `card`, `modal`, `form`, `badge`, `toggle`, `chart`, `navigation`,
`list-item`, `screen`, `tab`, `component` (fallback genérico)

## Arquivos afetados

| Arquivo | Mudança |
|---|---|
| `src/design_graph/graph/reader.py` | +`list_components()`, +`get_component_spec()` |
| `src/design_graph/mcp/tools.py` | +`list_components()`, +`get_component_spec()` tool handlers |
| `src/design_graph/mcp/tools.py` | Atualizar `TOOL_DEFINITIONS` com 2 novas tools |
| `tests/unit/graph/test_reader_advanced_queries.py` | Testes das novas queries |
| `tests/unit/mcp/test_tools.py` | Testes dos novos handlers |
