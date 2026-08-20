# T38 — Colapso de estilo consciente de ternário + nome de handler preservado

**Arquivos:** `src/design_graph/extraction/jsx_sanitizer.py`,
`src/design_graph/core/patterns.py`
**Depende de:** —
**Status:** `[x] done`

## Responsabilidade

Duas correções no mesmo arquivo, mesmo risco (parsing de JSX por regex),
por isso agrupadas: `_collapse_long_style_blocks` não pode mais truncar um
ternário no meio de um dos ramos, e o colapso de handler longo não pode
mais apagar o nome da prop de evento.

## Critério de aceite

- `style={{ prop: cond ? 'A' : 'B', ... }}` acima do limiar de colapso
  (`_STYLE_BLOCK_COLLAPSE_THRESHOLD`) preserva os dois ramos do ternário no
  preview resultante — não corta em `prop: cond ?,`.
- Ternário aninhado em template literal (`` `1px solid ${cond ? A : B}` ``)
  dentro de um bloco de estilo longo também preserva os dois ramos —
  mesmo padrão já validado em C13 para correlação de estado, reaplicado
  aqui ao colapso de estilo.
- Handler longo colapsado preserva o nome do evento (`onChange`, `onClick`,
  `onBlur`, etc.) no marcador resultante — nunca mais o literal genérico
  `on[handler]` sem contexto de qual prop era.
- Nenhuma regex nova usa lookahead/lookbehind aninhado sem limite — reusa
  `parsing.js_parser.find_matching_delimiter` (scanner balanceado O(n), já
  público desde C13) para localizar os limites reais do ternário/handler
  em vez de uma regex gulosa nova.
- Regressão: toda a suíte de `tests/unit/extraction/test_jsx_sanitizer.py`
  (comportamento de C21/C22 — proteção de markup cru, marcadores de
  lista/condicional/either, dedup de ícone) permanece verde sem alteração.
- Suíte completa (`pytest tests/unit/ -q`) sem regressão.

## Fora de escopo

- Reescrever o sanitizador para um parser de AST real — a decisão de usar
  scan balanceado + regex, não um parser JS completo, é anterior a este
  change (C01/C13) e continua válida; este task corrige dois pontos
  específicos, não a abordagem inteira.
- Qualquer marcador de lista/condicional/either (`{[list:…]}`,
  `{[conditional:…]}`, `{[either:…]}`) — comportamento intocado, já
  correto desde C21.
