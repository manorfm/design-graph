# Spec C29 — Estados hover/focus completos (Tailwind + correção de pareamento)

## Contexto

Quinta de 9 changes (C25–C33) motivada pela auditoria técnica completa do
pipeline (ver C25/spec.md). Dois problemas no mesmo eixo — produção de
`StyleEntry`/`InteractionEntry` com `state=hover`/`state=focus` — agrupados
por tocarem o mesmo tipo de dado e serem verificáveis pelo mesmo rebuild.

## Problemas identificados

### P1 — Variantes de estado Tailwind (`hover:`/`focus:`) descartadas por completo

`resolve_classes` (`parsing/css_class_resolver.py`) faz lookup exato de
classe (`rule_map.get(cls)` / `_TAILWIND_BUILTINS.get(cls)`), sem nunca
stripar um prefixo `algo:`. `className="bg-blue-500 hover:bg-blue-700"`
resolvia `bg-blue-500` normalmente e descartava `hover:bg-blue-700` por
inteiro — nenhum caminho do pipeline compensava isso para classes Tailwind
(só para CSS real com seletor `tag:pseudo-classe`, via C24/T45). Todo
resultado de `resolve_classes` sempre virava `StyleEntry(state=DEFAULT)`
(`StyleEntry.from_css_class` hardcodava o estado).

### P2 — Pareamento posicional de `onMouseEnter`/`onMouseLeave` cruza valores entre propriedades

Em `extract_component` (`extraction/component_extractor.py`), `enters` e
`leaves` (listas de `(prop, value)` extraídas de cada handler) eram
combinadas via `zip(enters, leaves)` — por **posição**, não por nome de
propriedade. Se o handler de saída restaura propriedades em ordem diferente
do handler de entrada (comum: `enter: {color, background}` /
`leave: {background, color}`), o `from_val` de uma propriedade era
atribuído à propriedade errada. Se os tamanhos divergem (enter seta 3
propriedades, leave só restaura 1), `zip()` trunca silenciosamente as
mutações de entrada excedentes — a interação inteira desaparece, não só o
`from_val`.

## Solução proposta

| Task | Problema | Camada |
|---|---|---|
| T61 | P1 | `parsing/css_class_resolver.py` + `core/models.py` (`StyleEntry.from_css_class`) |
| T62 | P2 | `extraction/component_extractor.py` |

**T61** — novo mapa `_STATE_PREFIXES = {"hover": StyleState.HOVER, "focus":
StyleState.FOCUS}`. Cada classe em `resolve_classes` é checada por um
prefixo `algo:` antes do lookup nos dois mapas; se o prefixo bate em
`_STATE_PREFIXES`, a parte após `:` é usada para o lookup e o `StyleEntry`
resultante carrega esse estado. **Escopo deliberadamente restrito a
hover/focus**: `StyleState` (`core/models.py`) só modela esses dois eixos
hoje — não há conceito de tema (`dark:`) nem breakpoint (`sm:`/`md:`/`lg:`)
no schema. Um prefixo fora do mapa (`dark:text-white`, `md:flex`) não é
stripado — a classe inteira falha os dois lookups e é descartada como
qualquer classe desconhecida, exatamente o comportamento de hoje. Tratá-la
como default seria estritamente pior (aplicaria um estilo condicional como
incondicional). `StyleEntry.from_css_class` ganha parâmetro `state` (mesmo
padrão já usado por `StyleEntry.create`), com a seed do id variando por
estado para não colidir com a entrada `default` da mesma classe/propriedade
— byte-compatível para o caso default (seed inalterada), confirmado por
teste.

**T62** — `enters`/`leaves` deixam de ser combinados via `zip()`. Em vez
disso, `leaves` é indexado num dict `prop → from_val` (primeira ocorrência
vence, mesmo padrão `seen_props`/`already_resolved` já usado em outros
pontos do arquivo); cada mutação de `enters` busca seu `from_val` pelo
próprio nome de propriedade. Uma propriedade sem restauração correspondente
em `leave` recebe `from_val=""` — mesma convenção que
`InteractionEntry.from_focus_mutation` já usa para "sem from_val
conhecido" — em vez de emprestar (incorretamente) o valor de outra
propriedade, ou desaparecer silenciosamente.

## Cobertura de testes exigida

- **P1/T61**: `TestResolveClassesStateVariants` (6 casos) — prefixo
  `hover:`/`focus:` resolvendo contra Tailwind builtin e contra
  `rule_map` custom; default e variante hover da mesma classe convivendo
  sem colisão de id; prefixo não suportado (`dark:`/`md:`) continua
  silenciosamente descartado; classe desconhecida após prefixo válido não
  produz entrada. `test_from_css_class_hover_state_seed_includes_state_name`
  + `test_from_css_class_default_and_hover_ids_differ` (core/models) —
  seed do estado default permanece byte-compatível
  (`test_from_css_class_matches_legacy_seed`, já existente, continua
  passando sem alteração).
- **P2/T62**: `test_reordered_leave_still_pairs_correct_from_val` — enter
  `{color, background}` / leave `{background, color}` (ordem invertida)
  resolve `from_val` correto para as duas propriedades.
  `test_enter_mutation_without_matching_leave_keeps_empty_from_val` — enter
  com 2 propriedades, leave restaurando só 1: a mutação sem correspondência
  continua produzindo uma interação (`from_val=""`), não é descartada.

Suíte completa (`pytest tests/unit/ -q`, `pytest tests/integration/ -q`) sem
regressão e guardrails (`pytest tests/test_architecture_guardrails.py -q`)
intactas; rebuild real contra `iPede Manager v21.2.html` (DB descartável em
`/tmp`) reportado no `plan.md`.

## Segurança

Nenhuma nova fronteira de I/O — as duas tasks continuam operando só sobre
texto já carregado do arquivo local do protótipo.

## Fora de escopo

- `dark:`/`sm:`/`md:`/`lg:` (e qualquer outro prefixo de variante Tailwind)
  — ver justificativa em T61; exigiria um eixo novo em `StyleState`/schema,
  sem evidência ainda de qual formato seria o certo para representar
  breakpoint/tema no grafo (mesma disciplina que C24 já aplicou a
  `styled-components`: não implementar sem evidência de padrão real).
- Ordem exata de merge quando `leaves` tem múltiplas mutações da mesma
  propriedade dentro do mesmo handler — `leave_by_prop.setdefault` mantém a
  primeira ocorrência, mesmo critério "primeiro vence" já usado em
  `already_resolved` (resolução de spread) e demais dedups do arquivo.
