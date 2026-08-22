# Spec C30 — Ordem de renderização (`order_index`)

## Contexto

Sexta de 9 changes (C25–C33) motivada pela auditoria técnica completa do
pipeline (ver C25/spec.md). Pré-requisito explícito para C31
(`get_component_full`): a nova tool precisa nascer já devolvendo filhos em
ordem, não alfabética.

## Problema identificado

### P1 — Ordem de renderização entre irmãos não é dado estruturado

`CONTAINS` (`graph/schema.py`) só carrega `weight INT64` (contagem de
ocorrência, hoje sempre `1` — nunca incrementado). A ordem visual dos filhos
de um componente só sobrevive dentro do `jsx_snippet` bruto. Confirmado em
código: `child_refs` era um `set[str]` durante toda a extração
(`extraction/component_extractor.py`), convertido para `sorted(child_refs)`
no retorno — ordem alfabética, não ordem de aparição. `consolidate()`
(`core/models.py`) repetia o mesmo padrão (`sorted({... para todas as
variantes})`). Um agente reconstruindo JSX a partir de `get_component`/
`get_screen_full` não tinha como saber a ordem visual real dos filhos sem
reler o JSX bruto — exatamente o tipo de informação que o grafo deveria
expor sem forçar isso.

## Solução proposta

| Task | Camada |
|---|---|
| T63 | `extraction/component_extractor.py` (captura ordenada) |
| T64 | `core/models.py` (`consolidate()` — decisão de qual variante manda) |
| T65 | `graph/schema.py` + `graph/writer.py` (persistência) |
| T66 | `graph/reader.py` (auditoria + `ORDER BY` nos 2 pontos que importam) |

**T63** — `child_refs` deixa de ser `set[str]`, vira `list[str]` com dedup
via `seen_child_refs` (mesmo padrão `seen_style_ids`/`seen_inter_ids` já
usado no arquivo para as outras listas). Ordem é aproximação documentada,
não byte-exata: `RE_JSX_TAG` é processado por completo antes de
`RE_COMP_REF` e `marker_refs` (mesma ordem de hoje), então a ordem final é
"por padrão, depois por posição dentro de cada padrão" — mesma classe de
aproximação que o projeto já aceita em outros pontos (ver T46/C24 sobre
ordem de merge de spread).

**T64** — decisão de design necessária quando há múltiplas declarações da
mesma função no bundle: `order_index` vem da variante **viva** (a última
declaração — mesmo critério que `_label_jsx_variants` já usa para decidir
qual `jsx_snippet` realmente executa, já que `variants[-1]` está
garantidamente em ordem de arquivo — `results` de `asyncio.gather`
preserva a ordem de `boundaries`, que vem de `find_all_boundaries` em ordem
textual). `consolidate()` usa a ordem do `child_refs` da variante viva
primeiro; filhos referenciados só por variantes mais antigas (sombreadas)
são apensados depois, na ordem em que aparecem — união preservada (nenhum
filho é perdido), só a precedência de ordem muda.

**T65** — `order_index INT64` na REL TABLE `CONTAINS` (mesmo padrão do
`weight INT64` já existente, schema `v8`). `_write_contains_edge` ganha
parâmetro `order_index`; `write_component` passa `enumerate(comp.child_refs)`.
Dedup de arestas (`_contains_keys`) **não muda** — já era garantida por uma
chave `"parent→child"` independente de `child_refs` ser set ou lista.
`_pending_contains` (caminho diferido, quando o filho ainda não foi
inserido) vira `set[tuple[str, str, int]]` para carregar o índice também
nesse caminho.

**T66** — auditoria das ~9 travessias `CONTAINS`/`CONTAINS*0..3` já
existentes em `reader.py`: a maioria alimenta buscas "quais telas usam este
componente" ou constrói dicts indexados por nome (ordem irrelevante para
esses casos). Duas de fato importam para reconstrução de tela:
`get_component_children` (1 hop direto, usado também por `get_component` e
`get_component_spec` via composição) e a query "Q11" dentro de
`get_screen_full` (constrói `children_by_comp` para a lista `"children"` de
cada componente na resposta). Ambas ganham `ORDER BY r.order_index` no
lugar de `ORDER BY c.name`/`child.name`. `get_screen_layout` foi verificado
e **não** usa CONTAINS (só `USES_COMPONENT` direto, lista plana de
componentes de topo, não uma árvore de irmãos) — não precisa de mudança.

## Cobertura de testes exigida

- **T63**: `TestChildRefsOrder` — ordem de aparição no JSX preservada;
  referência duplicada mantida só na primeira posição.
- **T64**: `TestExtractedComponentConsolidateChildOrder` — ordem vem da
  variante viva primeiro, com filhos só-na-variante-antiga apensados depois;
  filhos compartilhados não duplicam; variante única preserva sua própria
  ordem. Teste de regressão: `test_duplicate_definitions_are_consolidated_without_losing_variants`
  (já existente) atualizado — a asserção antiga (`["AlphaCard",
  "BetaCard"]`, alfabética) estava testando o comportamento antigo; a nova
  asserção (`["BetaCard", "AlphaCard"]`) reflete o critério correto
  (variante viva = a segunda declaração = `BetaCard` primeiro).
- **T65**: `test_order_index_persisted_in_declared_order`,
  `test_deferred_contains_edge_keeps_its_order_index` (confirma que o
  caminho diferido/`flush_pending_contains` também preserva o índice).
- **T66**: `test_get_component_children_returns_render_order_not_alphabetical`,
  `test_screen_full_children_follow_render_order`.

Suíte completa (`pytest tests/unit/ -q`, `pytest tests/integration/ -q`) sem
regressão (exceto a asserção corrigida acima, documentada como mudança de
comportamento intencional) e guardrails
(`pytest tests/test_architecture_guardrails.py -q`) intactas; rebuild real
contra `iPede Manager v21.2.html` (DB descartável em `/tmp`) reportado no
`plan.md`.

## Segurança

Nenhuma nova fronteira de I/O — mudança inteiramente sobre dado já
extraído/persistido localmente.

## Fora de escopo

- `get_screen_layout` — verificado e confirmado que não usa CONTAINS; fora
  de escopo por não se aplicar, não por decisão de escopo.
- Migração de bancos `.db` já existentes — o projeto já opera com rebuild
  completo + swap atômico (`GraphWriteSession`) para toda mudança de
  schema; não há caminho de migração incremental em nenhum change anterior,
  e este não introduz um.
