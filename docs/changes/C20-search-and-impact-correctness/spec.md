# Spec C20 — Correção crítica: busca sem cobertura de texto + impacto de token subestimado

## Contexto

Usuário pediu avaliação de maturidade pra produção, com foco explícito em:
busca não trazer elementos do protótipo, e informação incorreta/faltante/
errada quando um agente consulta o protótipo. Investigação (não pedido de
feature) achou 3 problemas reais, todos confirmados contra o grafo de
produção antes de qualquer correção.

## Problema 1 (crítico) — `search()` nunca indexava UIText

`mcp/search.py::_search_reader()` varria `Screen`, `Component` e `Token` —
nunca `UIText`. A própria descrição da tool MCP promete o contrário:
*"Search across screens, components, tokens **and texts**"*.

Confirmado contra o grafo real: `design-query search "Adicionar Componente"`
retornava **"Nenhum resultado"**, mesmo com o nó `UIText.content =
'Adicionar Componente'` existindo no grafo (confirmado via Cypher direto).
O grafo tem 1369 nós `UIText` — busca cobria **zero** deles. Como `UIText`
é onde vive o conteúdo visível real (rótulos, headings, mensagens), esse
é o tipo de busca que um agente mais faria — e sempre falhava
silenciosamente, sem nenhum erro, só "não encontrado".

## Problema 2 e 3 (alto) — impacto de token subestimava telas afetadas

Mesma causa-raiz já corrigida 3× no C18 (`get_screen_full`, `get_component`,
`get_component_spec`) — mas 2 pontos ficaram de fora porque o escopo do
C18 era reconstrução de tela, não análise de impacto:

- `find_token_usage()` — lista de telas só considerava
  `Screen-[:USES_COMPONENT]->Component` direto.
- `get_impact()` (caminho de token) — mesmo problema.

Um teste já existente (`test_screens_list_is_list_of_strings`) chegou a
**documentar o bug como comportamento esperado**: *"screens may be empty
if the component using the token is not directly linked to a screen via
USES_COMPONENT"* — o limite era conhecido mas nunca corrigido.

## Solução

1. `GraphReader.list_texts()` (novo) — `MATCH (t:UIText) RETURN
   t.id, t.content, t.text_type, t.source, t.element`. `_search_reader()`
   ganha um laço análogo aos de Screen/Component/Token, usando o mesmo
   `score_match()` já existente (nenhuma lógica de scoring nova).

2. `find_token_usage()` e `get_impact()` (caminho de token) — mesma
   expansão `-[:CONTAINS*0..3]->` já usada no C18.
   `find_token_usage` precisou de `WITH DISTINCT s, c` entre a expansão e o
   join com `Token` (mesma exigência do binder do Kuzu já documentada no
   C18); `get_impact` funcionou sem precisar disso (o padrão final já liga
   direto num nó com filtro de propriedade `{id:$tid}`, testado
   empiricamente).

## Impacto medido (real, pós-implementação)

```
design-query search "Adicionar Componente"
  Antes: "Nenhum resultado para 'Adicionar Componente'."
  Depois: 3 resultados (CompTab, IngPicker, OptRefPicker)

find_token_usage — token usado só via componente aninhado (fixture
  isolado CartItem→PriceTag): screens antes=[], depois=["RestaurantsPage"]
```

## Invariantes

- `list_texts()` não filtra por relevância — devolve todos os nós, o
  scoring já existente em `score_match()` decide o que aparece.
- Nenhuma mudança na contagem de nós/relações do grafo — as 3 correções
  são só na camada de leitura, rebuild real confirma stats idênticos ao
  baseline.

## Fora de escopo (registrado, não corrigido nesta rodada)

- `get_screen()` (a versão "overview", não `get_screen_full`) também só
  lista textos de componentes diretos — aceitável, já que a própria
  ferramenta se declara "overview" e direciona pra `get_screen_full`
  quando completude importa.

## Arquivos afetados

| Arquivo | Mudança |
|---|---|
| `src/design_graph/graph/reader.py` | `list_texts()` novo; `find_token_usage`/`get_impact` (token) expandidos via `CONTAINS*0..3` |
| `src/design_graph/mcp/search.py` | `_search_reader()` ganha laço sobre `list_texts()` |
| `tests/unit/mcp/test_search.py` | `TestSearchCoversUIText`; `_StubReader`/stubs ganham `list_texts()` |
| `tests/unit/mcp/test_tools.py` | `MockReader` ganha `list_texts()` |
| `tests/unit/graph/test_reader_advanced_queries.py` | testes de tela via componente aninhado pra `find_token_usage`/`get_impact`; comentário que documentava o bug como esperado removido |
