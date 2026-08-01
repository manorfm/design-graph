# T34 — Busca sem cobertura de UIText + impacto de token subestimado

**Arquivo:** `src/design_graph/graph/reader.py`, `src/design_graph/mcp/search.py`
**Depende de:** T14 (MCP search original), T32 (padrão CONTAINS*0..3, C18)
**Status:** ✅ done

## Responsabilidade

Fechar 3 gaps achados numa investigação de maturidade pra produção: busca
não indexava o tipo de conteúdo mais buscado (UIText), e 2 ferramentas de
análise de impacto subestimavam telas afetadas por não seguir `CONTAINS`.

## Critério de aceite

- `search()` encontra texto por conteúdo exato e por substring — testado
  com stub reader e confirmado contra o grafo real (`design-query search
  "Adicionar Componente"` → 3 resultados, antes 0).
- `find_token_usage`/`get_impact` (caminho de token) incluem telas que
  usam o token só através de um componente aninhado — testado com o
  fixture já existente (`CartItem` contém `PriceTag`).
- Nenhuma mudança na contagem de nós/relações do grafo.
- Suíte completa (`pytest -q`) sem regressão — 1570 testes.
- Rebuild real do prototype de referência com stats idênticos ao baseline;
  os 3 fixes confirmados contra o grafo de produção.
