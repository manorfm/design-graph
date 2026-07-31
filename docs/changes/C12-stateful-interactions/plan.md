# Plan C12 — Interações via estilo imperativo

## Objetivo

Capturar `Interaction` nós para handlers `onMouseEnter`/`onMouseLeave`/`onFocus`
que mutam `style` com um identificador ou expressão, não apenas com uma
string literal — sem regredir o caminho já coberto (literais).

## Critério de aceite

```bash
pytest tests/unit/extraction/test_component_extractor.py -k "HoverInteractionWithNonLiteralValues or hover" -v
pytest tests/unit/ -q   # suíte completa sem regressão
```

## Sequência TDD

### Fase 1 — regex captura expressão

**RED:** `test_hover_value_from_token_reference_is_captured` — `C.red` não
batia com `["\']([^"\']+)["\']`.

**GREEN:** trocar o grupo de valor para `([^;}]{1,80})` em
`RE_MOUSE_ENTER`/`RE_MOUSE_LEAVE`/`RE_ON_FOCUS`.

### Fase 2 — limpeza do valor capturado

**RED:** `test_literal_quoted_hover_value_still_unquoted` — com a regex nova,
um literal `'#f59e0b'` chegaria com as aspas incluídas em `to_val`/`from_val`.

**GREEN:** `_clean_style_value()` remove um par de aspas que envolve o valor
inteiro; aplicado nos três laços de `extract_component` (hover enter/leave,
focus) e na `StyleEntry` de estado `hover`.

### Fase 3 — expressão de concatenação

**RED:** `test_hover_value_from_expression_is_captured` — `color + '12'`.

**GREEN:** já coberto pela Fase 1 (a regex não distingue identificador de
expressão, captura tudo até `;`/`}`); `_clean_style_value` não encontra um
par de aspas envolvendo o texto inteiro e devolve como está.

## Validação end-to-end

Build real contra `iPede Manager v15.1.html` (fora da suíte de testes,
verificação manual):

```
interactions: 10 → 39
```

Nenhuma outra métrica do build regrediu (screens, components, tokens,
sections, contains, styles, texts todos estáveis ou levemente maiores pelo
fix de C02/OptRow aplicado na mesma sessão).
