# Spec C09 — Graph: Link Token → Propriedade de Estilo

## Problema

A aresta `USES_TOKEN` liga `Component → Token`. Isso responde "quais tokens esse
componente usa", mas não responde "em qual propriedade CSS esse token aparece".

Exemplos de perguntas impossíveis hoje:
- "O token `primary (#ffb81c)` é usado como `backgroundColor` ou `color`?"
- "Quais propriedades de `BtnPrimary` usam tokens do design system?"
- "Qual token define o padding do card?"

## Solução

Adicionar uma aresta `STYLE_USES_TOKEN` entre `Style` e `Token`:

```
Component ─[HAS_STYLE]→ Style ─[STYLE_USES_TOKEN]→ Token
```

Essa relação permite consultas como:

```cypher
-- "Qual token define backgroundColor de BtnPrimary no estado default?"
MATCH (c:Component {name:"BtnPrimary"})-[:HAS_STYLE]->(s:Style {state:"default", property:"backgroundColor"})
      -[:STYLE_USES_TOKEN]->(t:Token)
RETURN s.property, t.label, t.value
```

## Schema

Nova relação (schema.py):
```python
"CREATE REL TABLE STYLE_USES_TOKEN(FROM Style TO Token)"
```

Não tem propriedades — a aresta apenas conecta Style ao Token que resolve seu valor.

## Lógica de linkage no Writer

No método `write_component()`, após inserir cada `Style`, verificar se o valor
da propriedade casa com algum token do `token_map`:

```python
def _link_style_to_token(
    self,
    style: StyleEntry,
    token_map: dict[str, list[DesignToken]],
) -> None:
    """
    If style.value matches a token's value (exact or contains), create
    STYLE_USES_TOKEN edge from that Style to the Token.
    """
    normalized = style.value.strip().lower()
    for tokens in token_map.values():
        for token in tokens:
            if normalized == token.value.lower() or token.value.lower() in normalized:
                self._safe_execute(
                    "MATCH (s:Style {id:$sid}),(t:Token {id:$tid}) "
                    "CREATE (s)-[:STYLE_USES_TOKEN]->(t)",
                    {"sid": style.id, "tid": token.id},
                )
                return  # primeiro match vence — evita múltiplas arestas
```

## Reader — nova query

```python
def get_styles_with_tokens(self, comp_name: str) -> list[dict]:
    """
    Return styles for a component with their linked token (if any).
    Each dict: state, property, value, token_label, token_value, token_category.
    token_* fields are None when the style has no matched token.
    """
```

Query Cypher:
```cypher
MATCH (c:Component {name:$n})-[:HAS_STYLE]->(s:Style)
OPTIONAL MATCH (s)-[:STYLE_USES_TOKEN]->(t:Token)
RETURN s.state, s.property, s.value,
       t.label AS token_label, t.value AS token_value, t.category AS token_category
ORDER BY s.state, s.property
```

## Impacto em `get_component_spec` (C08)

Quando C08 e C09 estiverem ambos implementados, `get_component_spec` pode
enriquecer `styles_by_state` com a coluna Token:

```markdown
## Estilos — default
| Propriedade | Valor | Token |
|---|---|---|
| backgroundColor | #ffb81c | primary |
| borderRadius | 8px | radius_md |
| color | #fff | — |
```

## Invariantes

- O link é **best-effort**: se nenhum token casa, o Style existe sem aresta `STYLE_USES_TOKEN`
- Matching é case-insensitive e usa `contains` (para casos como `rgba(255,184,28,0.9)` vs `#ffb81c`)
- Uma Style tem no máximo **1** aresta `STYLE_USES_TOKEN` (primeiro match vence)
- Não altera os testes existentes de `write_component` — apenas adiciona comportamento

## Arquivos afetados

| Arquivo | Mudança |
|---|---|
| `src/design_graph/graph/schema.py` | +`STYLE_USES_TOKEN` rel table |
| `src/design_graph/graph/writer.py` | +`_link_style_to_token()`, chamado em `write_component` |
| `src/design_graph/graph/reader.py` | +`get_styles_with_tokens()` |
| `tests/unit/graph/test_writer_deduplication_guards.py` | Testes de linkage token→style |
| `tests/unit/graph/test_reader_advanced_queries.py` | Testes de `get_styles_with_tokens` |
