# Spec C18 — Eficiência de token na camada MCP

## Problema

Investigação dedicada (agente Explore) sobre se a camada MCP força um
agente a fazer múltiplas chamadas pra reunir contexto suficiente pra
reconstruir uma tela, e se alguma resposta carrega texto redundante sem
adicionar informação. Medido contra o grafo real de
`iPede Manager v15.1.html`. Quatro achados, todos aprovados pelo usuário:

### 1. `get_screen_full` não fecha a árvore de `CONTAINS`

Buscava componentes só pela relação direta `Screen-[:USES_COMPONENT]->Component`.
Um componente aninhado (só alcançável via `CONTAINS`) aparecia como nome na
lista `children` do pai, mas nunca com seus próprios estilos/tokens/props.

Medido em `InventoryPage` (maior tela real do prototype): 11 componentes
diretos retornados, mas **21 componentes únicos** de fato renderizados —
10 exigiam chamada extra, e um deles (`IconBtn`) estava aninhado 2 níveis,
seria perdido silenciosamente por um agente que só expandisse `children`
uma vez.

### 2. `get_component` e `get_component_spec` discordavam pra o mesmo componente

`get_component.screens_using` usava relação direta;
`get_component_spec.screens_using` usava `CONTAINS*0..3` (transitivo).
Medido: `get_component("Badge")` → 2 telas; `get_component_spec("Badge")`
→ 7 telas. Mesmo componente, mesmo banco, respostas diferentes.

### 3. Truncamento de tabela de estilo escondia propriedades inteiras

`StyleEntry` não colapsa "mesma propriedade, valores diferentes" (comum em
JSX condicional/mapeado: `color: i===2 ? a : 'white'`). O corte de 12
linhas cortava por **linha bruta**, não por propriedade distinta — medido
no `RestCard`: 28 linhas brutas / 17 propriedades distintas; as 12
primeiras linhas eram só 4 nomes repetidos, e `padding`/`gap`/
`gridTemplateColumns` nunca apareciam na tabela.

### 4. "Layout Profiles" em `get_screen_full` era 100% duplicado

~3% do payload repetindo, num formato diferente, dados que já apareciam
na tabela "Styles — default" de cada componente no mesmo documento.

## Solução

1. **Q5–Q11 de `get_screen_full`** (reader.py) expandidas de
   `Screen-[:USES_COMPONENT]->Component` pra
   `Screen-[:USES_COMPONENT]->Component-[:CONTAINS*0..3]->Component` (mesma
   profundidade já usada por `get_component_spec`/
   `find_screens_using_comp_transitively`). Kuzu exige `WITH DISTINCT`
   entre o hop de comprimento variável e qualquer padrão encadeado depois
   — sem isso o binder rejeita a query ("Variable X is not in scope").
   Contagem de queries continua fixa em 11 (O(1), não O(N)) — verificado
   por teste que monitora o número real de chamadas `_q()`.

2. **`get_component.screens_using`** passa a chamar
   `find_screens_using_comp_transitively()` — o mesmo método que
   `get_component_spec` já devia estar chamando (estava reimplementando a
   query inline, duplicada). As duas chamadas agora reusam literalmente o
   mesmo método.

3. **`_dedupe_styles_by_property()`** (novo helper, `tools.py`) — agrupa
   linhas de estilo por nome de propriedade antes do corte de 12, juntando
   valores distintos com `" | "`. O corte agora limita propriedades
   distintas, não linhas brutas. Aplicado nos dois lugares que truncavam
   do mesmo jeito (`get_screen_full`, `get_component_spec`).

4. Seção "Layout Profiles" removida da renderização Markdown de
   `get_screen_full`. O dado estruturado continua disponível no dict
   devolvido pelo reader (não removido de lá) e via `get_screen_layout`
   pra quem quiser só o resumo de layout sem os estilos completos.

## Impacto medido (real, pós-implementação)

- `get_screen_full("InventoryPage")`: 11 → **21 componentes** numa única
  chamada — `IconBtn` (2 níveis aninhado) confirmado presente com seus
  próprios estilos de hover. Elimina as 10 chamadas extras que seriam
  necessárias antes, e o risco de perdê-lo silenciosamente.
- `get_component("Badge")` e `get_component_spec("Badge")` agora
  concordam: 7 telas nos dois.
- `RestCard`/`ExcelModal`: todas as propriedades distintas de estilo
  voltam a aparecer na tabela, mesmo com >12 linhas brutas de origem.
- Payload de `get_screen_full` reduzido (~3%) sem perda de informação —
  Layout Profiles removida, dado idêntico já presente por componente.

## Invariantes

- Contagem de queries de `get_screen_full` continua O(1) — 11 queries
  fixas, testado explicitamente com contador de chamadas reais.
- Nenhuma mudança nos dados de extração/escrita do grafo — rebuild real
  do prototype de referência confirma stats idênticos ao baseline
  (components=173, interactions=72, etc.).
- `_dedupe_styles_by_property` nunca perde um valor: propriedades com
  múltiplos valores ficam com todos os valores distintos juntados, não
  com um escolhido arbitrariamente.

## Fora de escopo (adiado a pedido do usuário)

- Desambiguação de variantes de componente coladas (`ExtractedComponent.consolidate`
  junta implementações de código-fonte diferentes sob um só título "Source
  variant", sem indicar qual é usada em qual tela) — achado real, maior
  esforço de design, decisão explícita de deixar pra depois.

## Arquivos afetados

| Arquivo | Mudança |
|---|---|
| `src/design_graph/graph/reader.py` | Q5–Q11 de `get_screen_full` expandidas via `CONTAINS*0..3` + `WITH DISTINCT`; `get_component.screens_using` reusa `find_screens_using_comp_transitively`; `get_component_spec` para de duplicar essa query inline |
| `src/design_graph/mcp/tools.py` | `_dedupe_styles_by_property()`; removida seção "Layout Profiles" de `get_screen_full` |
| `tests/unit/graph/test_screen_full_query.py` | `TestGetScreenFullExpandsNestedComponents` + fixture `nested_screen_graph` |
| `tests/unit/graph/test_reader_advanced_queries.py` | `TestGetComponentScreensUsingDepth` |
| `tests/unit/mcp/test_style_dedup.py` (novo) | `_dedupe_styles_by_property`, cenário real do RestCard |
| `tests/unit/mcp/test_screen_full_tool.py` | `TestGetScreenFullToolDoesNotDuplicateLayoutSection` substitui `TestGetScreenFullToolLayoutOutput` |
