# T32 — Eficiência de token na camada MCP

**Arquivo:** `src/design_graph/graph/reader.py`, `src/design_graph/mcp/tools.py`
**Depende de:** T15 (MCPTools + MCPServer), T27 (get_screen_full original)
**Status:** ✅ done

## Responsabilidade

Fechar 4 gaps reais que forçavam chamadas MCP extras ou escondiam
informação real de um agente tentando reconstruir uma tela: lacuna de
`CONTAINS` em `get_screen_full`, inconsistência `get_component`/
`get_component_spec`, truncamento de estilo que cortava por linha em vez
de propriedade, e seção "Layout Profiles" duplicada.

## Critério de aceite

- `get_screen_full` retorna a closure completa de `CONTAINS` a partir dos
  componentes diretos da tela (profundidade `*0..3`, mesma já usada em
  `get_component_spec`) — componente aninhado 2 níveis confirmado presente
  com seus próprios dados no grafo real (`InventoryPage`/`IconBtn`).
- Contagem de queries de `get_screen_full` continua fixa em 11 (O(1)) —
  testado com contador real de chamadas, inclusive no cenário aninhado.
- `get_component.screens_using` e `get_component_spec.screens_using`
  reusam o mesmo método (`find_screens_using_comp_transitively`) —
  nenhuma duplicação de query, nenhuma resposta divergente pra o mesmo
  componente.
- `_dedupe_styles_by_property()` agrupa por propriedade antes do corte de
  12 linhas nos dois pontos que truncavam — nenhuma propriedade distinta
  desaparece por causa de valores repetidos vindos de JSX
  condicional/mapeado.
- Seção "Layout Profiles" removida da renderização de `get_screen_full`
  (dado 100% duplicado da tabela de estilo por componente); dado
  estruturado continua disponível via `get_screen_layout`.
- Suíte completa (`pytest -q`) sem regressão — 1562 testes.
- Rebuild real do prototype de referência com stats idênticos ao
  baseline; consultas reais confirmam os 4 fixes contra o grafo de
  produção.
