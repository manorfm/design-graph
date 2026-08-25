# Spec C34 — Correções de uma segunda rodada de auditoria (C25–C33)

## Contexto

Depois de C25–C33 (commits `a88d660`, `412045b`) estarem commitados, uma
segunda rodada de auditoria — 4 frentes em paralelo, revisão crítica do
código recém-escrito mais leitura de áreas nunca auditadas — encontrou 5
problemas reais, dois deles graves o suficiente para neutralizar parte do
valor entregue nos changes anteriores. Este change os corrige.

## Problemas identificados

### P1 — `apply_aliases` desfaz a ordenação do C30 inteira (crítico)

`extraction/alias_extractor.py:61` fazia
`sorted({aliases.get(ref, ref) for ref in refs})` — reordena alfabeticamente
E deduplica via `set`. `pipeline/coordinator.py` chama isso
incondicionalmente para **todo** componente/tela/seção assim que **qualquer**
alias existe em algum lugar do bundle, não só nos que de fato referenciam o
nome aliasado. `iPede Manager v21.2.html` — o protótipo de referência usado
em toda a implementação de C25–C33 — tem exatamente 1 alias (`{'Badge':
'Pill'}`), logado em todo rebuild feito durante aquela sessão. Resultado:
`child_refs` de **todos** os componentes desse protótipo eram re-ordenados
alfabeticamente depois de já terem sido corretamente ordenados por
`extract_all_components`/`consolidate()` (C30) — a observação registrada
em `docs/changes/C30-render-order/plan.md` ("ordem parece alfabética, não
consegui confirmar se é o código-fonte") era este bug, não uma coincidência
do bundle original.

### P2 — `flush_pending_contains` (C32) pode criar um Component fantasma com nome de Screen

Confirmado por evidência real: o rebuild do C32 mostrou 15 "componentes
unresolved" novos, 10 dos quais eram nomes de **Screen**
(`CategoriesPage`, `DashboardPage`, `RestaurantsPage`, `ItemEditorV6`,
etc.), não de componente. `write_component`'s loop de CONTAINS
(`graph/writer.py`) enfileira qualquer `child_ref` em `_pending_contains`
sem checar `_declared_screen_names` — diferente de `write_screen`, que já
faz essa checagem antes de decidir entre `USES_SCREEN` e
`_ensure_component_exists`. `flush_pending_contains` (C32) materializava um
node `Component` fantasma com o mesmo nome de uma `Screen` real já
existente.

### P3 — `validate_component_implementation` sem limite de tamanho (segurança)

`mcp/tools.py` — `jsx_source` (string arbitrária vinda de um agente,
potencialmente influenciada por prompt injection dentro do HTML do próprio
protótipo) era injetada direto num f-string e processada pelo mesmo
pipeline regex usado para bundles inteiros, sem nenhum limite de tamanho.
Superfície de custo computacional nova que não existia antes desta sessão.

### P4 — `screen_extractor.py`/`section_extractor.py` continuam alfabetizando `component_refs`

Mesma classe de problema que C30 resolveu para `CONTAINS`
(Component→Component), um nível acima: `USES_COMPONENT`
(Screen→Component) e `SECTION_USES` (Section→Component) continuavam vindo
de `sorted(set)`. Não estava documentado como "fora de escopo" em nenhum
spec — era um ponto cego, não uma decisão.

### P5 — `leave_by_prop.setdefault` mantém a primeira ocorrência, não a última

`extraction/component_extractor.py` (o próprio fix de C29 para o bug de
`zip()`) usa `leave_by_prop.setdefault(prop, val)` — mantém a **primeira**
ocorrência de uma propriedade dentro do mesmo handler `onMouseLeave`. Em
JS real, execução sequencial faz a **última** atribuição vencer. Mesma
classe de bug que C29 corrigiu, reintroduzida de forma mais sutil dentro
do próprio fix. `enters` tinha o problema análogo (nunca deduplicado por
propriedade, então duas mutações do mesmo prop no mesmo handler geravam
duas `InteractionEntry` em vez de uma).

## Solução proposta

| Task | Problema | Camada |
|---|---|---|
| T72 | P1 | `extraction/alias_extractor.py` |
| T73 | P2 | `graph/writer.py` |
| T74 | P3 | `mcp/tools.py` |
| T75 | P4 | `extraction/screen_extractor.py` + `extraction/section_extractor.py` |
| T76 | P5 | `extraction/component_extractor.py` |

**T72** — `apply_aliases` reescrito para preservar ordem: itera `refs`
mantendo um `seen: set[str]`, substitui alias→target, deduplica por
primeira ocorrência da forma resolvida — nunca ordena.

**T73** — `flush_pending_contains` pula (`continue`) qualquer `child` que
já esteja em `_declared_screen_names`, em vez de criar shell + aresta —
mesma guarda que `write_screen` já usa para seu próprio
`component_refs`/`section.component_refs`.

**T74** — nova constante `_MAX_VALIDATION_JSX_SOURCE_CHARS = 20_000`
(múltiplo generoso de `MAX_JSX_SNIPPET_CHARS=8_000`, nunca rejeita um
componente real). `validate_component_implementation` rejeita com mensagem
clara antes de processar quando `jsx_source` excede o limite.

**T75** — `_collect_component_refs` (screen_extractor.py) e o bloco de
component refs em `_build_section` (section_extractor.py) passam a usar o
mesmo padrão `seen`/lista já estabelecido por C30 em
`component_extractor.py`, em vez de `set`+`sorted()`.

**T76** — `enters`/`leaves` passam por um dict com atribuição incondicional
(`enters_by_prop[prop] = val`, não `.setdefault`) — mantém a posição da
primeira ocorrência para ordem de iteração, mas o **valor** reflete sempre
a última atribuição, igual à semântica real de execução sequencial do JS.

## Escopo deliberadamente não coberto

- **`order_index` real para `USES_COMPONENT`/`SECTION_USES`** — T75 corrige
  a ordem no nível do modelo de domínio (`ExtractedScreen`/
  `ExtractedSection.component_refs`), mas essas duas relações no schema
  Kuzu não têm uma propriedade de ordem como `CONTAINS` ganhou em C30, e
  várias queries em `reader.py` já usam `ORDER BY c.name` explícito para
  essas relações (ex.: `get_screen`, listas de "top_components"). Estender
  schema+writer+reader para essas duas relações é um esforço do mesmo
  porte do C30 inteiro — candidato a change própria (C35), não uma
  correção rápida de auditoria. T75 já é valor real por si só: corrige o
  dado na origem antes que qualquer consumidor futuro dependa dele.
- **Bancos `.db` antigos (pré-C28/C30) quebrando silenciosamente em toda
  leitura** — achado real da auditoria, mas é uma limitação já aceita do
  projeto (todo change de schema já exigia rebuild completo, sem caminho
  de migração incremental em nenhum change anterior); o gap é só a
  UX da falha (silenciosa, não uma mensagem clara de "schema
  desatualizado, rode --force"). Fora de escopo desta rodada de correções
  pontuais.
- **`--jsx` morto em `design-graph report`, janela de 600 chars sem log em
  `prop_extractor.py`, `chunker.py` sem marcador de truncamento, cobertura
  E2E das 3 tools novas do C31/C33** — achados reais da auditoria, mas sem
  relação com os 5 problemas críticos/altos que motivaram este change;
  candidatos a uma change própria se o objetivo continuar sendo fidelidade
  de reconstrução.

## Cobertura de testes exigida

- **P1/T72**: `test_preserves_original_appearance_order` (novo) +
  `test_substitutes_alias_with_target` (existente, asserção corrigida de
  alfabética para ordem de aparição).
- **P2/T73**: `test_child_matching_a_declared_screen_name_is_not_turned_into_a_shell`.
- **P3/T74**: `test_oversized_jsx_source_is_rejected_before_extraction`,
  `test_jsx_source_within_limit_is_processed_normally`.
- **P4/T75**: `test_component_refs_preserve_jsx_appearance_order` +
  `test_component_refs_have_no_duplicates` (screen_extractor, substituindo
  o teste antigo que afirmava ordem alfabética) + `TestSectionComponentRefsOrder`
  (2 casos, section_extractor).
- **P5/T76**: `test_repeated_property_in_leave_handler_uses_last_assignment`,
  `test_repeated_property_in_enter_handler_uses_last_assignment`.

Suíte completa (`pytest tests/unit/ -q`, `pytest tests/integration/ -q`) sem
regressão (exceto as 2 asserções corrigidas para refletir o comportamento
correto, documentadas acima) e guardrails
(`pytest tests/test_architecture_guardrails.py -q`) intactas; rebuild real
contra `iPede Manager v21.2.html` (DB descartável em `/tmp`) reportado no
`plan.md`.

## Segurança

T74 é a única mudança com superfície de segurança — reduz uma superfície de
custo computacional nova, sem introduzir nenhuma nova. As demais são
correções de correção/consistência de dado, sem mudança de fronteira de
I/O.
