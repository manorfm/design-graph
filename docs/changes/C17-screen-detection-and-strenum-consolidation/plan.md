# Plan C17 — Detecção de tela morta + consolidação de StrEnum

## Objetivo

Remover código morto e consolidar 4 definições independentes de
"string enum seguro" numa só, sem mudar comportamento observável.

## Critério de aceite

```bash
pytest tests/unit/extraction/test_screen_extractor.py -k StrBehavior -v
pytest tests/unit/core/test_graph_catalog.py -k EnumStrBehavior -v
pytest tests/unit/cli/test_validate_coverage.py -k ValidationSeverityStrBehavior -v
pytest tests/test_architecture_guardrails.py -q
pytest tests/unit/ -q   # suíte completa sem regressão
design-graph "iPede Manager v15.1.html" --force && design-graph validate --db "<db>"
# stats idênticos ao baseline; `design-graph db list` funciona (exercita
# GraphArtifactKind/GraphSelectionSource)
```

## Sequência

### Fase 1 — remoção de código morto (sem RED/GREEN — é remoção, não feature)

Confirmado por grep que `RE_SCREEN_FN`/`RE_SCREEN_NAME` não têm chamador
de produção. Removidas de `patterns.py`; teste que só testava a regex
isolada removido de `test_js_parser.py`; docstring de
`screen_extractor.py` corrigida.

### Fase 2 — consolidação StrEnum (RED → GREEN)

**RED:** um teste por enum migrado, provando o bug atual:
`str(ScreenIdentity.classify("RestaurantsPage").role) == "ScreenRole.PAGE"`
(não `"page"`); mesma coisa pra `GraphArtifactKind.DATABASE`,
`GraphSelectionSource.ONLY_DATABASE`, `ValidationSeverity.ERROR`.

**GREEN:** `_StrEnum` → `StrEnum` (público, `core/models.py`); os 4 enums
passam a herdar dele em vez de `(str, Enum)` cru.

### Fase 3 — regressão

Suíte completa + guardrails arquiteturais (G9/G11, já que `graph_catalog.py`
e `cli/validate.py` ganharam um novo import de `core.models` — confirmado
que ambos já são caminhos permitidos) + rebuild real do prototype de
referência.

## Nota sobre escopo

Não ampliei `ScreenIdentity.classify()` pra reincluir os sufixos que
`RE_SCREEN_NAME` tinha e ele não tem (`Panel`, `Tab`, `List`, `Section`,
`Modal`) — o teste parametrizado existente (`test_is_screen_classification`)
prova que a exclusão desses sufixos é **intencional e testada**, não um
esquecimento. Ampliar isso seria mudar comportamento sem justificativa —
fora do escopo desta change, que é só remover o código morto e consolidar
os enums.
