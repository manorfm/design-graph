# Spec C17 — Detecção de tela morta + consolidação de StrEnum

## Problema

Duas descobertas relacionadas, achadas investigando o que sobrou depois de
remover a duplicação do C16.

### 1. `RE_SCREEN_FN`/`RE_SCREEN_NAME` — regexes mortas com documentação mentirosa

O único chamador de produção de `RE_SCREEN_FN` era exatamente a função
duplicada removida em C16. Sem ele, a regex ficou sem nenhum uso real —
só sobrevivia via um teste que exercitava a regex isoladamente, sem testar
nenhuma funcionalidade real.

`RE_SCREEN_NAME` já não tinha nenhum uso de produção **antes mesmo do
C16** — só aparecia numa frase de docstring em `screen_extractor.py`
("A function is a Screen if its name ends in one of the semantic suffixes
defined by RE_SCREEN_NAME"), que é **falsa**: a classificação de tela real
sempre foi feita por `ScreenIdentity.classify()`, um classificador
propositalmente mais restrito (exclui `Panel`/`Tab`/`List`/`Section`/`Modal`
— confirmado por teste parametrizado existente com casos explícitos como
`("ProfileModal", False)`, `("BillList", False)`, `("MenuSection", False)`).

`git log -S` confirma a origem: `RE_SCREEN_NAME` foi a implementação
*original* (spec T07, change C02) — `ScreenIdentity`/`ScreenRole` vieram
depois como refinamento (evitar classificar `ConfirmModal`/`SettingsPanel`
como tela), e ninguém voltou pra remover a regex órfã nem corrigir a
docstring.

### 2. `ScreenRole` e mais 3 enums redefinindo `(str, Enum)` de forma independente

`ScreenRole` (screen_extractor.py), `GraphArtifactKind`/`GraphSelectionSource`
(core/graph_catalog.py) e `ValidationSeverity` (cli/validate.py) — nenhum
usa o `StrEnum` compartilhado criado no C14 (então chamado `_StrEnum`,
privado). Nenhum tinha bug *ativo* hoje — cada um evita o problema por
disciplina manual (`.value` explícito em toda formatação), não por
garantia estrutural. É exatamente a mesma fragilidade que motivou criar
`StrEnum` em primeiro lugar: basta um f-string futuro esquecer `.value`
pra reintroduzir "ClassName.MEMBER" no output.

## Solução

- Removidas `RE_SCREEN_FN`/`RE_SCREEN_NAME` de `patterns.py`; teste que só
  exercitava a regex morta removido; docstring de `screen_extractor.py`
  corrigida pra descrever `ScreenIdentity.classify()` (o classificador
  real) em vez da regex morta.
- `_StrEnum` (privado, `core/models.py`) promovido a `StrEnum` (público) —
  agora usado por 4 módulos, não só o domínio.
- `ScreenRole`, `GraphArtifactKind`, `GraphSelectionSource`,
  `ValidationSeverity` migrados de `(str, Enum)` pra `StrEnum`.

## Invariantes

- `is_screen()`/`ScreenIdentity.classify()` continua sendo a única fonte
  de verdade pra "isso é uma tela" — nenhuma mudança de comportamento,
  só remoção do código morto que nunca era consultado.
- `str(member)` de qualquer um dos 4 enums migrados produz o valor puro,
  não `"ClassName.MEMBER"` — testado explicitamente pra cada um.
- Nenhuma mudança de comportamento observável no grafo — rebuild real do
  prototype de referência confirma stats idênticos ao baseline.

## Arquivos afetados

| Arquivo | Mudança |
|---|---|
| `src/design_graph/core/patterns.py` | remove `RE_SCREEN_FN`, `RE_SCREEN_NAME` |
| `src/design_graph/extraction/screen_extractor.py` | docstring corrigida; `ScreenRole` usa `StrEnum` |
| `src/design_graph/core/models.py` | `_StrEnum` → `StrEnum` (público) |
| `src/design_graph/core/graph_catalog.py` | `GraphArtifactKind`/`GraphSelectionSource` usam `StrEnum` |
| `src/design_graph/cli/validate.py` | `ValidationSeverity` usa `StrEnum` |
| `tests/unit/parsing/test_js_parser.py` | remove teste da regex morta |
| `tests/unit/extraction/test_screen_extractor.py`, `tests/unit/core/test_graph_catalog.py`, `tests/unit/cli/test_validate_coverage.py` | testes de `__str__` pros 4 enums migrados |
