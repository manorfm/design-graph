# Plan C13 — Completude na captura de interações

## Objetivo

Fechar os dois gaps deixados fora de escopo por C12: handlers com múltiplas
mutações de estilo, e o padrão `useState(bool)` + ternária de estilo — sem
regredir nenhum caminho já coberto.

## Critério de aceite

```bash
pytest tests/unit/extraction/test_component_extractor.py -k "MultiStatementHoverHandlers or StateToggleHoverInteractions" -v
pytest tests/unit/ -q   # suíte completa sem regressão
```

## Sequência TDD

### Fase 1 — isolamento de corpo de handler por chaves balanceadas

**RED:** `test_both_mutated_properties_captured` — handler com duas mutações
(`borderColor` e `background`); regex antiga (`onMouseEnter[^;]{0,60}style\.`)
só encontra a primeira.

**GREEN:** `js_parser.find_matching_delimiter()` expõe publicamente
`JavaScriptFunctionScanner._matching_delimiter` (já testado internamente para
limites de função). `re_event_handler_open(event)` localiza a `{` de
abertura; `_handler_mutations(window, event)` isola o corpo até a `}` de
fechamento correspondente e aplica `RE_STYLE_MUTATION` (genérica) sobre o
corpo isolado — capturando todas as mutações, não só a primeira.

### Fase 2 — pareamento enter/leave permanece por posição

**RED:** `test_second_property_pairs_enter_with_matching_leave` — a segunda
mutação do handler de entrada precisa casar com a segunda mutação do handler
de saída (mesma ordem relativa).

**GREEN:** já coberto pela Fase 1 — `enters`/`leaves` agora são listas
"achatadas" (todas as mutações de todos os handlers, na ordem em que os
handlers aparecem no JSX), e o `zip()` existente pareia por posição. Validado
contra o prototype real, onde toda mutação encontrada mantém a mesma ordem
de propriedades nos dois handlers.

### Fase 3 — correlação estado booleano → ternária de estilo

**RED:** `test_ternary_inside_template_literal_captured` — `const [hov,
setHov] = useState(false)` + `onMouseEnter/Leave` que só chamam o setter +
`border: \`1px solid ${hov ? A : B}\`` — nenhuma mutação de `style.prop =`
existe, então nenhum caminho anterior encontra essa interação.

**GREEN:** `RE_USE_STATE_BOOL` + `re_state_setter_trigger()` +
`re_state_ternary_style()` (todos em `patterns.py`); novo bloco em
`extract_component` que: (1) encontra pares estado/setter, (2) confirma
associação com hover ou focus via presença do setter no handler certo, (3)
busca a ternária correspondente na mesma `window`.

### Fase 4 — isolamento por componente evita correlação cruzada

**RED:** `test_reused_state_var_name_does_not_cross_contaminate_siblings` —
dois componentes irmãos, ambos com `const [hov, setHov] = useState(false)`
mas valores de ternária diferentes (`C.red` vs `C.green`).

**GREEN:** já garantido pela Fase 3 — a busca ocorre em `window =
js[boundary.start:boundary.end]`, que `find_function_boundaries` já garante
não ter overlap entre componentes irmãos (T02/T15).

### Fase 5 — nenhum falso positivo sem par enter/leave

**RED:** `test_no_false_positive_without_enter_leave_pair` — `useState(bool)`
usado só para um `onClick`, sem `onMouseEnter`/`onMouseLeave`/`onFocus`.

**GREEN:** já coberto — o bloco de correlação exige `has_enter and
has_leave`, ou um `onFocus`, antes de buscar a ternária; sem isso, `continue`.

## Validação end-to-end

Build real contra `iPede Manager v15.1.html` (fora da suíte de testes,
DB descartável em `/tmp`, nunca a DB de produção):

```
Unresolved:    1 → 0   (herdado do fix de C02, sessão anterior)
Interactions: 39 → 64  (C12 → C13; 10 → 64 desde o baseline original)
Styles:     3539 → 3595
```

Nenhuma outra métrica regrediu (screens, tokens, sections, contains, props
todos estáveis ou levemente maiores).
