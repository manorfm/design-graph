# T45 — Resolução de seletor de tag + pseudo-classe (`input:focus`)

**Arquivos:** `src/design_graph/parsing/css_class_resolver.py`,
`src/design_graph/extraction/component_extractor.py`
**Depende de:** T44 (sem CSS chegando a `sources.css`, esta task não tem
nenhum insumo real para resolver contra em prototypes `bundled_react`)
**Status:** `[x] done`

## Responsabilidade

`extract_css_rules` (`css_class_resolver.py`) só casa `.classe { ... }` —
a própria docstring documenta a exclusão deliberada de pseudo-classes e
seletores de elemento, correta para seletor de CLASSE (não dá pra saber
se um elemento tem uma className sem examinar o JSX), mas essa
justificativa não vale para seletor de TAG pura: o nome da tag renderizada
já basta. `NumInput` (`<input type="number">`) não recebe nenhuma
interação de foco mesmo com a regra `input:focus, select:focus,
textarea:focus { outline: none; border-color: #FFB81C !important;
box-shadow: 0 0 0 3px rgba(255,184,28,0.12); }` presente no CSS real do
protótipo (texto verificado em `iPede Manager v15.1.html`).

## Nota de implementação

`StyleEntry.create()` deriva o id de `(element, state, property, value)`
— um componente que renderiza duas tags nativas diferentes (`<input>` e
`<select>`, por exemplo) mas resolve a mesma propriedade/valor pra ambas
sob o mesmo `element=nome_do_componente` colidiria num único id, perdendo
uma das duas entradas. Resolvido passando `element=f"{nome}:{tag}"`
(ex. `"LoginForm:input"`) só neste caminho — `StyleEntry.create()` em si
não mudou, nenhum outro call site é afetado, e `element` já não é
exibido em nenhuma saída MCP (confirmado: só vira propriedade interna do
nó `Style` no grafo), então não há mudança de formato visível.

## Critério de aceite

- Nova função em `css_class_resolver.py`, com nome e contrato próprios —
  **não** uma extensão de `resolve_classes` (que documenta seu contrato
  como indexado por className; misturar tag-selector ali quebraria essa
  promessa de responsabilidade única). Parseia listas de seletor
  compartilhando um corpo (`tag:pseudo, tag:pseudo, ... { propriedades }`)
  em um mapa `tag → pseudo-classe → propriedades`.
- `component_extractor.py` consulta esse mapa pelo nome de tag HTML
  nativa que o próprio componente renderiza (`input`, `select`,
  `textarea`, ...) e grava as propriedades resolvidas como
  `StyleEntry`/`InteractionEntry` no estado `hover`/`focus`
  correspondente — mesmo vocabulário de estado já usado pelas interações
  vindas de handler JS (C12/C13), nenhum estado novo inventado.
- `input:focus, select:focus, textarea:focus { ... }` real do protótipo:
  um componente que renderiza `<input>` ganha a interação de foco com
  `border-color: #FFB81C`; um componente que só renderiza `<div>` não é
  afetado.
- Seletor único (`input:focus { ... }`, sem lista) resolve igual.
- Suíte completa (`pytest tests/unit/ -q`) sem regressão; guardrails
  G1/G2 intactas (`css_class_resolver.py` continua em `parsing/`, sem
  import de `extraction/`/`graph/`/`mcp/`).

## Fora de escopo

- Especificidade/cascata real de CSS (uma regra mais específica
  sobrescrevendo esta) — mesma aproximação simplificada que o resto do
  resolvedor de CSS já aceita (fallback Tailwind, sem modelo de
  precedência formal).
- Seletor combinando tag E classe (`input.large:focus`) — não encontrado
  nos prototypes de referência; escopo é tag pura, como o caso real.
