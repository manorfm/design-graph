# Spec C21 — Colapso de expressões dinâmicas com escaneamento balanceado

## Problema

Reportado pelo usuário: ao gerar uma página real a partir do prototype
`ipede_manager_v15.1` (tela `ItemsPage`), o agente não recuperou
corretamente a tag/badge de "Em Destaque" de `ItemCard`, precisou de
correção manual para o modelo do botão, e a estrelinha de destaque só
apareceu de forma inconsistente entre componentes.

Investigação via `get_screen_full`/`get_full_jsx` (MCP) contra o grafo
real confirmou o dado já corrompido na origem — mesmo `get_full_jsx`
(que devolve o `jsx_snippet` sem o corte de tamanho do `CappedJsx`, mas
ainda o mesmo texto já sanitizado) mostrava:

```jsx
{[conditional:Badge]} color={C.blue} />}
{[conditional:Badge]} />}
```

## Causa raiz

`RE_JSX_SHORT_CIRCUIT` e `RE_JSX_TERNARY_COMPONENTS`
(`core/patterns.py`, usadas por `sanitize_jsx` em
`extraction/component_extractor.py`) capturavam o corpo do componente
colapsado com uma cauda de regex gananciosa e não balanceada:

```python
r'\{[^{}<>&]{1,120}&{2}\s*<([A-Z][A-Za-z0-9]+)[^}]{0,400}\}'
```

`[^}]{0,400}` para na **primeira** `}` que encontra. Um prop tão comum
quanto `color={C.red}` já fornece essa `}` bem antes do fim real da
expressão JSX — o match termina no meio do prop, e o resto do JSX original
(` />}`) sobra como texto cru colado logo depois do marcador. `RE_JSX_MAP_RENDER`
tinha exatamente a mesma falha estrutural.

Um segundo gap, independente, no mesmo `sanitize_jsx`: markup cru
(`<span>`/`<svg>`, sem nome de componente PascalCase) dentro de um
`{cond && (...)}` — caso do ícone de estrela — nunca é reconhecido pelos
marcadores (eles só disparam para `<ComponentName>`), então sua
sobrevivência dependia do fallback genérico `RE_LONG_TERNARY = r'\{[^{}]{300,}\}'`:
sobrevive se tiver menos de 300 caracteres, e é apagado silenciosamente
para `{...}` (zero informação, nem o nome da tag) se passar disso. Um
corte invisível amarrado à contagem de caracteres, não a uma decisão de
design.

## Solução

Escaneamento por chaves balanceadas, não regex de cauda — reaproveitando
`parsing.js_parser.find_matching_delimiter`, já usado em outros pontos do
mesmo pipeline (`extract_return_block`, isolamento de handler de evento em
`extract_component`).

- `core/patterns.py`: as 3 regex antigas (`RE_JSX_MAP_RENDER`,
  `RE_JSX_SHORT_CIRCUIT`, `RE_JSX_TERNARY_COMPONENTS`) viram regex **de
  cabeça apenas** (`RE_JSX_LIST_HEAD`, `RE_JSX_CONDITIONAL_HEAD`,
  `RE_JSX_EITHER_HEAD`) — casam só até `<ComponentName`, nunca tentam
  achar o fim. O fim real vem de `find_matching_delimiter` a partir da
  `{` de abertura. Duas novas regex de cabeça (`RE_JSX_MARKUP_CONDITIONAL_HEAD`,
  `RE_JSX_MARKUP_EITHER_HEAD`) reconhecem o mesmo formato para tag
  minúscula, usadas só para proteger o span do fallback genérico — nunca
  para colapsar (colapsar destruiria a única cópia do markup visual).

- `core/models.py`: `JsxMarker` (value object, `frozen dataclass`) +
  `JsxMarkerKind` (`StrEnum`) — valida no `__post_init__` que
  `LIST`/`CONDITIONAL` tenham exatamente 1 nome e `EITHER` exatamente 2;
  `__str__` é a única fonte de verdade do formato textual do marcador
  (`{[kind:Name]}` / `{[either:A|B]}`), substituindo 3 closures
  quase-idênticas que formatavam a string cada uma à sua maneira.

- `extraction/jsx_sanitizer.py` (novo módulo — antes vivia dentro de
  `component_extractor.py`, que já tinha responsabilidade própria de
  extração por componente): `sanitize_jsx` público, e por trás dele uma
  única função `_collapse_marked_regions(jsx, head, kind)` reutilizada
  para os 3 casos (list/conditional/either) em vez de 3 blocos quase
  duplicados — cada um recebia sua própria regex de cabeça e produzia seu
  `JsxMarker`. Uma segunda função, `_protected_markup_spans`, calcula os
  spans balanceados de markup cru a proteger; `_collapse_long_expressions`
  aplica o fallback genérico pulando esses spans.

## Por que markup cru nunca vira marcador

Um componente colapsado (`{[conditional:Badge]}`) não perde informação de
forma irrecuperável — `get_component_spec('Badge')` devolve o shape real
do componente. Markup cru (um `<svg>` de ícone) não tem esse fallback: o
marcador *é* a única cópia da forma visual. Por isso a proteção existe
como um mecanismo à parte, que preserva o span inteiro em vez de resumi-lo
— e por isso ele não tem limite de tamanho embutido (o corte geral de
exibição já é responsabilidade do `CappedJsx`, na camada MCP, que rotula
claramente o que cortou em vez de apagar sem aviso).

## O que foi deliberadamente deixado de fora

A rotulagem de variantes "shadowed"/"live" de JSX duplicado (`Btn`/`Modal`
com 2 declarações no prototype real) — mecanismo do C19, já funcionando
corretamente e coberto por teste. O gap real ali não é de extração, é de
visibilidade do rótulo para quem consome — fora do escopo deste fix a
pedido explícito do usuário.

## Invariantes

- Nenhum marcador colapsado pode conter texto de JSX cru sobrando depois
  dele — verificado para prop com chave aninhada em todos os 3 tipos
  (list/conditional/either), então-branch e else-branch.
- Um markup cru condicional/ternário sobrevive inteiro independente do
  tamanho — não depende mais de contagem de caracteres.
- O fallback genérico (`RE_LONG_TERNARY`) continua colapsando expressões
  longas não relacionadas a markup/componente (ex.: cálculo inline longo).
- `_extract_marker_refs`/`child_refs` (não alterados) continuam
  funcionando sem mudança — o formato textual do marcador é idêntico ao
  anterior para os casos que já funcionavam.
