# Spec C28 — Truncamento como dado, não log

## Contexto

Quarta de 9 changes (C25–C33) motivada pela auditoria técnica completa do
pipeline (ver C25/spec.md). Esta é a categoria de achado mais crítica para o
propósito do produto: o agente de IA consulta o grafo em vez de reler o HTML,
e confia no que recebe. Quando a extração trunca um componente e isso só
aparece em `logger.debug`, o agente recebe uma spec "completa" que não é —
sem qualquer forma de saber disso.

## Problema identificado

### P1 — Caps de extração truncam sem deixar rastro no grafo

`extract_component` (`extraction/component_extractor.py`) aplica os limites
`MAX_STYLES_PER_COMPONENT`, `MAX_INTERACTIONS_PER_COMPONENT`,
`MAX_TEXTS_PER_COMPONENT`, `MAX_CLASSES_PER_COMPONENT` (`core/constants.py`)
inline, durante a coleta. Um `_cap()` local já calcula corretamente se cada
campo foi cortado, mas só para compor uma linha de `logger.debug` — que
nunca chega ao build output, a `design-graph validate`, nem a nenhuma tool
MCP (`get_component`, `get_component_spec`, `get_screen_full`). Confirmado no
rebuild de referência: **36 de 177 componentes** do `iPede Manager v21.2.html`
têm pelo menos um campo truncado (majoritariamente `styles`, alguns
`texts`) — 36 respostas MCP hoje se apresentam como completas sem ser.

## Solução proposta

| Task | Camada |
|---|---|
| T56 | `extraction/component_extractor.py` (cálculo) |
| T57 | `core/models.py` (`ExtractedComponent.truncated_fields` + `consolidate()`) |
| T58 | `graph/schema.py` + `graph/writer.py` (persistência) |
| T59 | `graph/reader.py` (exposição via `get_component`/`get_component_spec`/`get_screen_full`) |
| T60 | `mcp/tools.py` (aviso na resposta Markdown) |

**Padrão seguido** (já estabelecido no projeto, não inventado aqui): "o fato
sobre o valor vive perto do próprio valor" — mesmo espírito de `CappedJsx`
(`mcp/tools.py`, com `.was_cut`/`.notice()`), `JsxSnippet`
(`core/models.py`, com `.was_sanitized`) e `PropDefault` (com
`.was_declared`). Aqui a unidade não é uma única string (são 4 listas
independentes que podem ser cortadas separadamente), então o formato
correto é um `frozenset[str]` nomeando quais campos foram cortados — não um
booleano solto, que perderia a informação de *qual* campo.

**T56** — ao final de `extract_component`, computa
`truncated_fields = frozenset({name for name, count, limit in (...) if count >= limit})`
reaproveitando exatamente a mesma comparação que `_cap()` já fazia para o
log — nenhuma lógica nova de detecção, só um novo destino para o resultado.

**T57** — `ExtractedComponent` ganha `truncated_fields: frozenset[str]`.
`consolidate()` propaga como união entre variantes: se qualquer variante do
mesmo componente bateu um cap, o componente consolidado carrega esse fato —
o merge de variantes não "recupera" dado que foi cortado durante a extração
de uma variante individual, então a união é a leitura conservadora correta.

**T58** — novo campo `truncated_fields STRING` no node `Component`
(`schema.py`, `v7`), serializado como string separada por vírgula (mesmo
padrão simples já usado para `classes`, que também é uma lista curta de
tokens). `writer.py` grava em toda escrita de `Component` (criação, update,
e shell de referência não-resolvida, que sempre grava `''`).

**T59** — `c.truncated_fields` adicionado ao `RETURN` das 3 queries que hoje
buscam campos base do `Component` (`get_component`, `get_component_spec`,
e a query de componentes de `get_screen_full`); `_assemble_screen_full`
expõe como lista já separada (`"truncated_fields": [...]`, chave sem
prefixo `c.`, consistente com o resto da montagem desse dict).

**T60** — novo helper `_truncated_fields_notice(truncated_fields,
recoverable_via=None)` em `mcp/tools.py`, aceitando tanto a string bruta
(`get_component`/`get_component_spec`) quanto a lista já separada
(`get_screen_full`) — mesmo fato, duas formas intermediárias diferentes.
Devolve um aviso Markdown nomeando os campos cortados e sugerindo
`get_full_jsx(name)` quando aplicável (mesmo texto/estilo de
`CappedJsx.notice()`). Ligado nas 3 tools de leitura de componente.

## Cobertura de testes exigida

- **T56/T57**: `test_styles_cap_recorded_in_truncated_fields`,
  `test_classes_cap_recorded_in_truncated_fields`,
  `test_no_caps_hit_yields_empty_truncated_fields`,
  `test_consolidate_unions_truncated_fields_across_variants`.
- **T58**: `test_truncated_fields_persisted_as_sorted_csv`,
  `test_no_truncation_persisted_as_empty_string`.
- **T59**: `TestTruncatedFieldsRoundTrip` — `get_component`,
  `get_component_spec` e `get_screen_full` cada um confirmado surfaçando o
  valor persistido, nas suas respectivas formas (string vs lista).
- **T60**: `TestTruncatedFieldsNoticeHelper` (7 casos do helper isolado) +
  `TestTruncatedFieldsNotice` (4 casos via `ToolDispatcher`, cobrindo as 3
  tools + caso "nada truncado" sem aviso espúrio).

Suíte completa (`pytest tests/unit/ -q` e `pytest tests/integration/ -q`)
sem regressão e guardrails (`pytest tests/test_architecture_guardrails.py
-q`) intactas; rebuild real contra `iPede Manager v21.2.html` (DB
descartável em `/tmp`) reportado no `plan.md`.

## Segurança

Nenhuma nova fronteira de I/O — campo adicional persistido e lido pelo
mesmo caminho já existente para `classes`.

## Fora de escopo

- Persistir *quantos* itens foram cortados (só *quais campos*) — o valor
  informacional de "styles foi cortado, chame get_full_jsx" já resolve o
  problema real (o agente sabe que deve buscar a fonte bruta); um contador
  exato exigiria mais um campo por categoria sem mudar a ação que o agente
  toma.
- Aplicar o mesmo tratamento a outros truncamentos identificados na
  auditoria mas fora deste componente específico (buffer de cores em
  `token_extractor.py`, corte de 5 componentes em `chunker.py`, descarte de
  textos >80 caracteres em `TextEntry.is_plausible_content`) — cada um vive
  em um extrator diferente com sua própria forma de dado; generalizar
  `truncated_fields` para todos eles é uma mudança maior, candidata a change
  própria se houver evidência de que o agente é afetado na prática.
