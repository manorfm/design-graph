# Plan C20 — Busca sem cobertura de texto + impacto de token

## Objetivo

Corrigir os 3 achados da investigação de maturidade, sem regredir nada.

## Critério de aceite

```bash
pytest tests/unit/mcp/test_search.py -k CoversUIText -v
pytest tests/unit/graph/test_reader_advanced_queries.py -k nested_component -v
pytest tests/unit/ -q   # suíte completa
design-graph "iPede Manager v15.1.html" --force
design-query search "Adicionar Componente" --db "<db>"   # deve achar 3 resultados
```

## Sequência TDD

### Fase 0 — investigação e confirmação do bug (antes de qualquer teste)

Confirmado contra o grafo de produção via `design-query search` e Cypher
direto: `search()` não indexa `UIText`. Confirmado via script isolado
(fixture CartItem→PriceTag) que `find_token_usage`/`get_impact` perdem a
tela quando o token só é usado por um componente aninhado.

### Fase 1 — RED: busca cobre UIText

`TestSearchCoversUIText` (novo, `test_search.py`) — stub reader com
`list_texts()` retornando 2 textos; busca por conteúdo exato e por
substring falha (nenhum resultado tipo "UIText"). `_StubReader` existente
e `MockReader` (test_tools.py) precisaram de `list_texts()` adicionado só
pra não quebrar com `AttributeError` quando o laço novo for chamado —
constatado rodando a suíte completa depois do GREEN, não antecipado.

### Fase 2 — GREEN: busca cobre UIText

`GraphReader.list_texts()` + laço em `_search_reader()` reusando
`score_match()` sem nenhuma lógica de scoring nova.

### Fase 3 — RED: impacto de token via componente aninhado

Reusado o fixture `rich_graph` já existente (`test_reader_advanced_queries.py`)
— já tinha exatamente a topologia certa (`CartItem` direto na tela,
`CartItem-[:CONTAINS]->PriceTag`, `PriceTag` usa o token de cor). Dois
testes novos, um por método, ambos falhando com `screens == []`.

### Fase 4 — GREEN: impacto de token via CONTAINS

`find_token_usage`: `WITH DISTINCT s, c` entre a expansão `CONTAINS*0..3`
e o join com `Token` — sem isso, o binder do Kuzu rejeita (mesma
exigência já documentada no C18). `get_impact`: expansão direta funcionou
sem `WITH DISTINCT` — testado empiricamente antes de assumir.

## Validação end-to-end

Rebuild real (stats idênticos ao baseline — mudança é só na camada de
leitura). `design-query search "Adicionar Componente"` passa de "nenhum
resultado" pra 3 resultados reais (`CompTab`, `IngPicker`, `OptRefPicker`).
