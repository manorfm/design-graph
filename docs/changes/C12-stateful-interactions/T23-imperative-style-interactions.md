# T23 — Interações via estilo imperativo (hover/focus sem literal)

**Arquivo:** `src/design_graph/core/patterns.py`, `src/design_graph/extraction/component_extractor.py`
**Depende de:** T06 (ComponentExtractor)
**Status:** ✅ done

## Responsabilidade

Reconhecer `onMouseEnter`/`onMouseLeave`/`onFocus` que mutam
`style.prop = <expressão>` quando `<expressão>` é um identificador
(`C.red`), uma referência de prop (`o.color`) ou uma expressão simples
(`color + '12'`) — não apenas uma string literal.

## Critério de aceite

- `RE_MOUSE_ENTER`/`RE_MOUSE_LEAVE`/`RE_ON_FOCUS` capturam o valor como texto
  bruto até `;` ou `}`.
- `_clean_style_value()` remove aspas envolventes de literais; deixa
  identificadores/expressões intactos.
- Testes novos em `test_component_extractor.py::TestHoverInteractionWithNonLiteralValues`
  cobrindo: token reference, expressão de concatenação, literal (regressão),
  `onFocus` com token.
- Suíte completa (`pytest -q`) sem regressão.
