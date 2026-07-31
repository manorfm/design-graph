# Plan C14 — Classificação de texto de tooltip

## Objetivo

Diferenciar `title`/`aria-label`/`alt` de conteúdo textual visível, sem
duplicar entradas nem regredir a extração de texto existente.

## Critério de aceite

```bash
pytest tests/unit/core/test_models.py -k TestTextType -v
pytest tests/unit/extraction/test_component_extractor.py -k TooltipTextExtraction -v
pytest tests/unit/ -q   # suíte completa sem regressão
```

## Sequência TDD

### Fase 1 — novo membro de enum

**RED:** `TestTextType.test_members` — `"tooltip"` ausente do conjunto
esperado.

**GREEN:** `TextType.TOOLTIP = "tooltip"` em `models.py`.

### Fase 2 — captura via regex dedicada

**RED:** `test_title_attribute_captured_as_tooltip`,
`test_aria_label_attribute_captured_as_tooltip` — `CloseButton` com
`title="Fechar"` e `aria-label="Fechar modal"`; nenhum texto com
`text_type="tooltip"` existe ainda.

**GREEN:** `RE_TOOLTIP_TEXT` em `patterns.py`; novo laço em
`extract_component` chamando `_add_text(m.group(1), TextType.TOOLTIP)`.

### Fase 3 — precedência no dedup

**RED:** `test_tooltip_text_not_duplicated_as_generic_label` — sem ordenar
o laço de tooltip antes do laço genérico `RE_UI_STRING`, `"Fechar"` seria
capturado primeiro como `label` (a regex genérica roda antes na ordem
original do arquivo) e o dedup por id (`(source, content)`) descartaria a
tentativa de classificá-lo como `tooltip` depois.

**GREEN:** laço de `RE_TOOLTIP_TEXT` posicionado antes do laço de
`RE_UI_STRING` no corpo de `extract_component`.

## Validação end-to-end

Build real contra `iPede Manager v15.1.html` (fora da suíte de testes, DB
descartável): confirmar que os 143 valores de `title` antes classificados
como `label` agora aparecem como `tooltip`, e que a contagem total de
`UIText` não regride (nenhum texto perdido, só reclassificado + eventuais
novos textos que a regex genérica não capturava).
