# T27 — Classificação de texto de tooltip (title/aria-label/alt)

**Arquivo:** `src/design_graph/core/patterns.py`, `src/design_graph/core/models.py`, `src/design_graph/extraction/component_extractor.py`
**Depende de:** T06 (ComponentExtractor)
**Status:** ✅ done

## Responsabilidade

Reconhecer `title=`/`aria-label=`/`alt=` como texto descritivo distinto de
conteúdo visível — essencial para botões só-com-ícone, onde é o único sinal
textual do que o elemento faz.

## Critério de aceite

- `RE_TOOLTIP_TEXT` captura o valor de `title`/`aria-label`/`alt`.
- `TextType.TOOLTIP` novo membro do enum.
- Laço de extração roda antes de `RE_UI_STRING` — texto de tooltip vence o
  dedup por id `(source, content)` em vez de ser capturado como `label`
  genérico.
- Testes novos em `test_models.py::TestTextType` e
  `test_component_extractor.py::TestTooltipTextExtraction`.
- Suíte completa (`pytest -q`) sem regressão.
