# T26 — Nomes de componente/tela com dígito (ItemCardV6, KDSPageV7)

**Arquivo:** `src/design_graph/core/patterns.py`
**Depende de:** —
**Status:** ✅ done

## Responsabilidade

Reconhecer nomes PascalCase que contêm dígitos (comum em componentes
versionados: `ItemCardV6`, `KDSPageV7`, `Step2Form`) em toda regex que
identifica nome de componente/tela — não apenas letras.

## Contexto

Descoberto durante a validação end-to-end de C13: `ItemCardV6` não aparecia
em nenhuma consulta (`design-query inspect ItemCardV6` retornava vazio)
apesar do componente existir no prototype com o padrão exato coberto por
T25 (useState + ternária). Causa raiz: `RE_COMP_FN`/`RE_COMP_ARROW_FN` usam
`[A-Z][a-zA-Z]{2,}` — a classe de caracteres do corpo do nome não inclui
dígitos, então o match falha inteiro na primeira ocorrência de um dígito
(não trunca o nome, invalida o match porque o `\(` seguinte não bate).

O mesmo problema afetava `RE_SCREEN_FN`/`RE_SCREEN_NAME` (telas inteiras
como `ItemsPageV6`, `SectorsPageV6`, `PricingPageV6`, `TemplatesPageV6`,
`CompGroupsPageV6` ficavam invisíveis como tela), `RE_JSX_TAG` (referência
como filho ao usar `<ItemCardV6 />`), `RE_JSX_CALL` e `RE_COMP_REF`.

## Critério de aceite

- `[A-Z][a-zA-Z]{2,}`/`[A-Z][a-zA-Z]+` → `[A-Z][a-zA-Z0-9]{2,}`/`[A-Z][a-zA-Z0-9]+`
  em `RE_COMP_FN`, `RE_COMP_ARROW_FN`, `RE_SCREEN_FN`, `RE_SCREEN_NAME`,
  `RE_JSX_TAG`, `RE_JSX_CALL`, `RE_COMP_REF`.
- Testes novos: `test_js_parser.py::TestVersionedComponentNames`,
  `test_component_extractor_single_pass_guards.py::TestVersionedComponentChildRef`.
- Suíte completa sem regressão.

## Impacto medido

No prototype `iPede Manager v15.1.html`: 8 componentes/telas passam de
completamente invisíveis para totalmente extraídos —
`ItemCardV6`, `ItemsPageV6`, `SectorsPageV6`, `PricingPageV6`,
`TemplatesPageV6`, `CompGroupsPageV6`, `KDSPageV7`, `ItemEditorV6`.
