# T35 — Colapso balanceado de expressões dinâmicas em JSX

**Arquivos:** `src/design_graph/extraction/jsx_sanitizer.py` (novo),
`src/design_graph/core/models.py`, `src/design_graph/core/patterns.py`,
`src/design_graph/extraction/component_extractor.py`,
`src/design_graph/mcp/tools.py`
**Depende de:** T22 (C11, sistema de marcadores tipados original)
**Status:** ✅ done

## Responsabilidade

Garantir que `sanitize_jsx` nunca produza um marcador corrompido (JSX cru
sobrando depois de `{[conditional:X]}` etc.) quando o componente
colapsado tem props com chave própria, e que markup cru condicionalmente
renderizado sobreviva de forma determinística, não amarrada à contagem de
caracteres.

## Critério de aceite

- `JsxMarker`/`JsxMarkerKind` (`core/models.py`) — value object validado:
  `LIST`/`CONDITIONAL` exigem exatamente 1 nome de componente, `EITHER`
  exige exatamente 2; `ValueError` no `__post_init__` caso contrário.
- `RE_JSX_LIST_HEAD`/`RE_JSX_CONDITIONAL_HEAD`/`RE_JSX_EITHER_HEAD`
  (`core/patterns.py`) substituem as antigas `RE_JSX_MAP_RENDER`/
  `RE_JSX_SHORT_CIRCUIT`/`RE_JSX_TERNARY_COMPONENTS` — casam só a cabeça
  da expressão; o fim vem de `find_matching_delimiter`.
- `RE_JSX_MARKUP_CONDITIONAL_HEAD`/`RE_JSX_MARKUP_EITHER_HEAD` protegem
  markup cru (`<span>`/`<svg>` sem componente nomeado) do fallback
  genérico `RE_LONG_TERNARY`, independente do tamanho.
- `extraction/jsx_sanitizer.py` (novo módulo) — `sanitize_jsx` movido de
  `component_extractor.py`; `_collapse_marked_regions` reutilizada para
  os 3 tipos de marcador em vez de 3 blocos quase-duplicados.
- Nenhum marcador colapsado deixa JSX cru sobrando — testado para prop
  com chave aninhada nos 3 tipos, então-branch e else-branch.
- Markup cru condicional/ternário sobrevive inteiro mesmo acima de 300
  caracteres — antes virava `{...}` sem nenhuma informação.
- Comportamento pré-existente sem regressão: 8 testes de
  `TestExistingBehaviourUnchanged` cobrindo os casos que já funcionavam
  antes (marcador simples, `.map`, ternário, handler longo, texto
  estático, blocos de estilo).
- Testes de `sanitize_jsx` duplicados em 2 arquivos de teste consolidados
  em `test_jsx_sanitizer.py`, dono único da função.
- `mcp/tools.py`: descrição de `get_full_jsx` corrigida — não devolve
  JSX "unsanitized", devolve o `jsx_snippet` sanitizado sem o corte de
  tamanho do `CappedJsx`.
- Guardrails de arquitetura (G1/G2) intactas — `jsx_sanitizer.py` só
  importa de `core/`/`parsing/`.
- Suíte completa (`pytest -q`) sem regressão: 1620 passando, mesmas 5
  falhas pré-existentes (`ModuleNotFoundError: mcp`, ausente no venv,
  confirmado idêntico antes e depois via `git stash`).

## Fora de escopo

Rotulagem "shadowed"/"live" de variantes de JSX duplicado (C19) — já
funciona corretamente, mecanismo existente não alterado a pedido
explícito do usuário.
