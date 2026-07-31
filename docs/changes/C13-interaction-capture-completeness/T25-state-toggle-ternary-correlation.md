# T25 — Correlação estado booleano → ternária de estilo

**Arquivo:** `src/design_graph/core/patterns.py`, `src/design_graph/extraction/component_extractor.py`
**Depende de:** T23 (C12), T24 (isolamento de handler)
**Status:** ✅ done

## Responsabilidade

Reconhecer o padrão `const [state, setState] = useState(bool)` +
`onMouseEnter/Leave` (ou `onFocus`) que só chamam `setState(true|false)` +
uma expressão ternária `prop: state ? A : B` em outro ponto do JSX do mesmo
componente — inclusive quando a ternária está aninhada em um template
literal.

## Critério de aceite

- `RE_USE_STATE_BOOL` reconhece a declaração do par estado/setter.
- `re_state_setter_trigger(setter, event)` confirma a associação entre o
  setter e o evento DOM que o aciona.
- `re_state_ternary_style(state)` encontra `prop: state ? A : B`, incluindo
  o caso `` prop: `...${state ? A : B}...` ``.
- Interação só é emitida quando há par `onMouseEnter`+`onMouseLeave`
  (trigger "hover") ou `onFocus` (trigger "focus") associado ao setter —
  `useState(bool)` isolado não produz falso positivo.
- Busca sempre escopada à `window` do componente — nomes de estado
  reutilizados (`hov`, `h`) em componentes irmãos não se correlacionam entre
  si.
- Testes novos em `test_component_extractor.py::TestStateToggleHoverInteractions`,
  incluindo teste explícito de não-correlação cruzada entre irmãos.
- Suíte completa (`pytest -q`) sem regressão.
