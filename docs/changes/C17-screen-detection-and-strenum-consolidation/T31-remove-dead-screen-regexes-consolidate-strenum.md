# T31 — Remover regexes de tela mortas, consolidar StrEnum

**Arquivo:** `src/design_graph/core/patterns.py`, `src/design_graph/core/models.py`, `src/design_graph/extraction/screen_extractor.py`, `src/design_graph/core/graph_catalog.py`, `src/design_graph/cli/validate.py`
**Depende de:** T27 (StrEnum original, então `_StrEnum`), T30 (C16 — removeu o último chamador de `RE_SCREEN_FN`)
**Status:** ✅ done

## Responsabilidade

Eliminar 2 regexes órfãs (uma delas com docstring que mentia sobre qual
mecanismo realmente classifica telas) e consolidar 4 definições
independentes de `(str, Enum)` numa base `StrEnum` compartilhada.

## Critério de aceite

- `RE_SCREEN_FN`/`RE_SCREEN_NAME` removidas de `patterns.py` — zero
  chamadores de produção confirmado por grep antes da remoção.
- Docstring de `screen_extractor.py` descreve `ScreenIdentity.classify()`
  corretamente (não mais `RE_SCREEN_NAME`).
- `_StrEnum` → `StrEnum` (público) em `core/models.py`.
- `ScreenRole`, `GraphArtifactKind`, `GraphSelectionSource`,
  `ValidationSeverity` herdam de `StrEnum` — `str(member)` produz o valor
  puro nos 4 casos, testado explicitamente.
- Suíte completa (`pytest -q`) sem regressão — 1549 testes.
- Guardrails arquiteturais (G9, G11) continuam passando com os novos
  imports de `core.models`.
- Rebuild real do prototype de referência com stats idênticos ao
  baseline; `design-graph db list` (exercita os enums de
  `graph_catalog.py`) funciona normalmente.
