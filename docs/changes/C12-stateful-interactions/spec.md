# Spec C12 — Extraction: interações via estilo imperativo (hover/focus sem literal)

## Problema

`RE_MOUSE_ENTER`, `RE_MOUSE_LEAVE` e `RE_ON_FOCUS` só reconhecem o padrão:

```jsx
onMouseEnter={e => e.currentTarget.style.background = '#333'}
```

A captura do valor exige uma string literal entre aspas
(`["\']([^"\']+)["\']`). Prototypes reais raramente escrevem cores como
literais soltos — referenciam um objeto de tokens compartilhado ou compõem
a cor via expressão:

```jsx
onMouseEnter={e => e.currentTarget.style.borderColor = C.red}
onMouseEnter={e => e.currentTarget.style.background = color + '12'}
```

Nenhum dos dois casos acima batia com a regex antiga — o handler existe,
mas o grafo não registra nenhuma `Interaction`.

### Impacto medido

No prototype `iPede Manager v15.1.html` (165 componentes, sem uma única
classe Tailwind `hover:`/`focus:` — todo o feedback visual é feito via
`onMouseEnter`/`onMouseLeave` mutando `style` diretamente):

| Métrica | Antes | Depois |
|---|---|---|
| `onMouseEnter` no código-fonte | 61 | — |
| `onMouseEnter` com valor literal (capturado antes) | 21 | — |
| `Interaction` nós no grafo | 10 | 39 |

## Solução

Ampliar a captura do valor de `["\']([^"\']+)["\']` (string literal) para
`([^;}]{1,80})` (qualquer expressão até `;` ou `}`), e limpar o resultado em
`extract_component`: se o texto capturado estiver totalmente entre aspas,
remove as aspas (mantém o comportamento antigo para literais); caso
contrário mantém o identificador/expressão como está
(`C.red`, `color + '12'`, `o.color`).

```python
def _clean_style_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1].strip()
    return value
```

## Invariantes

- Comportamento anterior preservado para literais quotados — nenhuma regressão
  nos testes existentes (`BTN_JS` com `'#f59e0b'`).
- Um handler continua contribuindo no máximo uma propriedade `style.X = Y`
  (a primeira encontrada após `onMouseEnter`/`onMouseLeave`/`onFocus`) — mesma
  limitação de single-pass já presente antes desta change, não alargada nem
  reduzida.
- Valores vazios após a limpeza são descartados (não geram `Interaction`
  nem `StyleEntry`).

## Fora de escopo

- O padrão alternativo `onMouseEnter={() => setHover(true)}` com estilo
  condicional em `style={{...: hover ? A : B}}` (toggle de estado React, sem
  mutação direta do DOM) — exige correlacionar o nome da variável de estado
  entre o handler e a expressão condicional em outro ponto do JSX; não
  coberto por esta change. No prototype de referência é ~20% dos casos
  (12 de 61 `onMouseEnter`).
- Handlers com múltiplas propriedades mutadas (`style.a = X; style.b = Y;`)
  continuam capturando apenas a primeira.

## Arquivos afetados

| Arquivo | Mudança |
|---|---|
| `src/design_graph/core/patterns.py` | `RE_MOUSE_ENTER`/`RE_MOUSE_LEAVE`/`RE_ON_FOCUS` — valor captura expressão, não só literal |
| `src/design_graph/extraction/component_extractor.py` | `_clean_style_value()` + aplicação nos três pontos de uso |
| `tests/unit/extraction/test_component_extractor.py` | `TestHoverInteractionWithNonLiteralValues` |
