# T24 — Handlers com múltiplas mutações de estilo

**Arquivo:** `src/design_graph/parsing/js_parser.py`, `src/design_graph/core/patterns.py`, `src/design_graph/extraction/component_extractor.py`
**Depende de:** T23 (C12 — `_clean_style_value`)
**Status:** ✅ done

## Responsabilidade

Capturar todas as mutações `style.prop = valor` dentro de um único handler
(`onMouseEnter`/`onMouseLeave`/`onFocus`), não apenas a primeira.

## Critério de aceite

- `js_parser.find_matching_delimiter()` — wrapper público sobre
  `JavaScriptFunctionScanner._matching_delimiter`, usado para isolar o corpo
  do handler entre `{` e `}` balanceados (tratando strings/template
  literals/comentários).
- `re_event_handler_open(event)` localiza a abertura do handler;
  `RE_STYLE_MUTATION` (genérica, sem nome de evento) aplicada ao corpo já
  isolado captura toda mutação `style.prop = valor`.
- `RE_MOUSE_ENTER`/`RE_MOUSE_LEAVE`/`RE_ON_FOCUS` removidas de
  `patterns.py` — substituídas pelo par acima.
- `_handler_mutations(window, event)` em `component_extractor.py` substitui
  o uso direto das três regexes antigas nos três pontos (enter, leave,
  focus).
- Testes novos em `test_component_extractor.py::TestMultiStatementHoverHandlers`.
- Suíte completa (`pytest -q`) sem regressão.
