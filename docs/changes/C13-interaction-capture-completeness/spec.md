# Spec C13 — Extraction: completude na captura de interações

## Problema

C12 corrigiu a captura de valores não-literais em `style.prop = value`, mas
deixou dois gaps documentados como "fora de escopo":

### 1. Handlers com múltiplas mutações de estilo

```jsx
onMouseEnter={e => {
  e.currentTarget.style.borderColor = o.color;
  e.currentTarget.style.background = o.color + '0c';
}}
```

A extração antiga localizava o texto literal `onMouseEnter` e capturava
apenas o **primeiro** `style.prop =` encontrado depois dele — a segunda
mutação (e qualquer mutação adicional) era descartada silenciosamente.

### 2. Padrão de estado React (toggle) em vez de mutação imperativa

```jsx
const [hov, setHov] = useState(false);
...
onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
style={{
  border: `1px solid ${hov ? C.accent + '55' : C.border}`,
  boxShadow: hov ? `0 0 0 1px ${C.accent}22, 0 4px 20px #0005` : 'none',
}}
```

Aqui não existe nenhuma mutação de `style` no handler — o handler só alterna
um booleano de estado, e o valor real de cada propriedade vem de uma
expressão ternária em outro ponto do JSX. Esse padrão era completamente
invisível ao grafo antes desta change.

### Impacto medido

No prototype `iPede Manager v15.1.html` (mesma referência usada em C12):

| Métrica | C12 (baseline) | C13 (depois) |
|---|---|---|
| `Interaction` nós no grafo | 39 | 64 |
| Handlers `onMouseEnter` com 2+ mutações de estilo | não capturados além da 1ª | todas capturadas |
| Pares `useState(bool)` + `onMouseEnter`/`onMouseLeave` correlacionados | 0 | 12 |

## Solução

### 1. Isolamento do corpo do handler por contagem de chaves balanceada

`js_parser.find_matching_delimiter()` (wrapper público sobre
`JavaScriptFunctionScanner._matching_delimiter`, já usado internamente para
encontrar o fim de funções) é reaproveitado para encontrar o `}` que fecha
`<event>={...}`, já tratando strings/template literals/comentários. Toda
mutação `style.prop = valor` dentro desse corpo isolado é capturada — não só
a primeira.

`RE_MOUSE_ENTER`/`RE_MOUSE_LEAVE`/`RE_ON_FOCUS` (regexes que amarravam nome
do evento + primeira mutação em uma única expressão) são substituídas por
`re_event_handler_open(event)` (localiza a abertura do handler) +
`RE_STYLE_MUTATION` (genérica, aplicada ao corpo já isolado).

### 2. Correlação de estado booleano → ternária de estilo

Dentro da mesma `window` do componente (que já é exatamente o corpo dessa
função, sem overlap com irmãos — propriedade garantida por
`find_function_boundaries`):

1. `RE_USE_STATE_BOOL` encontra `const [state, setState] = useState(bool)`.
2. `re_state_setter_trigger(setState, event)` confirma que esse setter é
   chamado dentro de `onMouseEnter`/`onMouseLeave` (→ trigger "hover") ou
   `onFocus` (→ trigger "focus").
3. `re_state_ternary_style(state)` encontra `prop: state ? A : B` — inclusive
   quando a ternária está aninhada dentro de um template literal
   (`` `1px solid ${state ? A : B}` ``).

Escopar por `window` (não pelo arquivo inteiro) é essencial: nomes de
variável de estado como `hov`/`h` se repetem em dezenas de componentes
irmãos no mesmo arquivo — uma busca global correlacionaria o handler de um
componente com a ternária de outro.

## Invariantes

- Comportamento de C12 preservado integralmente — literais, tokens e
  expressões continuam capturados e normalizados por `_clean_style_value`.
- Pareamento `enter`/`leave` por posição (`zip`) é preservado; múltiplas
  mutações por handler mantêm a mesma ordem relativa entre o handler de
  entrada e o de saída (verificado no prototype real — todas as mutações
  pareadas mantêm a mesma ordem de propriedades nos dois handlers).
- Interações do padrão de estado usam os mesmos IDs determinísticos
  (`_hid`) e o mesmo conjunto `seen_inter_ids` que as interações
  imperativas — nenhuma duplicação possível entre os dois caminhos.
- `useState(bool)` sem par `onMouseEnter`+`onMouseLeave` (ou `onFocus`)
  associado ao setter não produz interação — evita falsos positivos em
  estados booleanos não relacionados a hover/focus.

## Fora de escopo

- Estado de hover controlado por CSS puro (`:hover` em stylesheet) — já
  coberto por caminho separado (resolução de classes CSS, C10).
- Handlers que chamam o setter indiretamente (`onMouseEnter={setHov.bind(null, true)}`,
  ou um handler nomeado que só é definido em outro componente) — a correlação
  exige a chamada literal `setter(true|false)` dentro do próprio atributo.
- Ternárias cujo branch verdadeiro/falso contém `:` sem estar entre aspas
  (ex.: um objeto literal inline) podem cortar a captura prematuramente —
  não observado no prototype de referência, mas é uma limitação conhecida
  da abordagem por regex (sem AST).

## Arquivos afetados

| Arquivo | Mudança |
|---|---|
| `src/design_graph/parsing/js_parser.py` | `find_matching_delimiter()` — wrapper público |
| `src/design_graph/core/patterns.py` | `RE_STYLE_MUTATION`, `re_event_handler_open()`, `RE_USE_STATE_BOOL`, `re_state_setter_trigger()`, `re_state_ternary_style()`; remove `RE_MOUSE_ENTER`/`RE_MOUSE_LEAVE`/`RE_ON_FOCUS` |
| `src/design_graph/extraction/component_extractor.py` | `_handler_mutations()`; bloco de correlação estado→ternária |
| `tests/unit/extraction/test_component_extractor.py` | `TestMultiStatementHoverHandlers`, `TestStateToggleHoverInteractions` |
