# Plan C18 — Eficiência de token na camada MCP

## Objetivo

Fechar os 4 achados aprovados pelo usuário após a investigação, cada um
validado por TDD e pelo grafo real, mantendo `get_screen_full` O(1) em
número de queries.

## Critério de aceite

```bash
pytest tests/unit/mcp/test_screen_full_tool.py -v
pytest tests/unit/graph/test_reader_advanced_queries.py -k ScreensUsingDepth -v
pytest tests/unit/mcp/test_style_dedup.py -v
pytest tests/unit/graph/test_screen_full_query.py -v
pytest tests/unit/ -q   # suíte completa sem regressão
design-graph "iPede Manager v15.1.html" --force && design-graph validate --db "<db>"
# stats idênticos ao baseline (mudança é só na camada de leitura)
```

## Sequência TDD (ordem de risco crescente)

### Fase 1 — remover "Layout Profiles" duplicado (trivial)

RED: `TestGetScreenFullToolDoesNotDuplicateLayoutSection` — a seção
continua presente no output. GREEN: bloco de renderização removido de
`tools.py`; dado continua no dict do reader (não é uma mudança de dado,
só de apresentação).

### Fase 2 — consistência `get_component` vs `get_component_spec`

RED: `TestGetComponentScreensUsingDepth` (fixture `deep_graph` — 3
componentes aninhados, screen usa só o topo) — `get_component("DeepLeaf")`
não encontra a tela, `get_component_spec` encontra. GREEN:
`get_component.screens_using` chama `find_screens_using_comp_transitively()`;
`get_component_spec` também passa a chamar o mesmo método em vez de
duplicar a query inline.

### Fase 3 — dedup de estilo antes do truncamento

RED: `TestDedupeStylesByProperty` (função pura) +
`TestStyleTruncationNoLongerHidesDistinctProperties` (cenário RestCard
real: 28 linhas brutas, 17 propriedades distintas, `padding` cortado pelo
cap de 12). GREEN: `_dedupe_styles_by_property()` agrupa por propriedade
antes do slice `[:12]`, nos dois pontos de truncamento (`get_screen_full`,
`get_component_spec`).

### Fase 4 — fechar o CONTAINS em `get_screen_full` (maior risco)

RED: `TestGetScreenFullExpandsNestedComponents` (fixture `nested_screen_graph`
— `TopCard -[CONTAINS]-> MidBadge -[CONTAINS]-> DeepIcon`, screen usa só
`TopCard`) — `MidBadge`/`DeepIcon` ausentes de `result["components"]`.

GREEN, primeira tentativa: trocar `-[:USES_COMPONENT]->(c:Component)` por
`-[:USES_COMPONENT]->(top:Component)-[:CONTAINS*0..3]->(c:Component)-[:HAS_STYLE]->(st:Style)`
em Q6–Q11 — **falhou** com "Binder exception: Variable c is not in
scope" pra todas as 6 queries que encadeiam um padrão depois do hop de
comprimento variável. Kuzu não permite estender um pattern diretamente
após `*N..M` do mesmo jeito que Neo4j/openCypher.

Correção: `WITH DISTINCT c` entre o MATCH que expande a closure e o MATCH
que junta o próximo relacionamento — verificado manualmente contra um
banco de teste antes de aplicar nas 6 queries. GREEN confirmado, incluindo
o teste de contagem de queries (`test_query_count_stays_bounded_with_nested_components`,
≤13 queries, mesma regra já aplicada ao caso não-aninhado).

## Validação end-to-end

Rebuild real do `iPede Manager v15.1.html` (stats idênticos ao baseline —
mudança é só na camada de leitura, não na extração). Consultas reais
contra o grafo:

```
get_screen_full("InventoryPage") → 11 → 21 componentes; IconBtn
  (2 níveis aninhado) confirmado presente com estilos de hover próprios.
get_component("Badge") vs get_component_spec("Badge") →
  ambos agora retornam as mesmas 7 telas (antes: 2 vs 7).
```
