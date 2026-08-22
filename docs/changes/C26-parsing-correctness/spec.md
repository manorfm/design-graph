# Spec C26 — Correções de bugs de parsing (except genérico, div não-balanceado, spread ambíguo)

## Contexto

Segunda de 9 changes (C25–C33) motivada pela auditoria técnica completa do
pipeline (ver C25/spec.md). Três bugs de correção independentes, sem relação
entre si além de todos produzirem dado incompleto ou errado sem erro visível
— agrupados aqui porque nenhum exige mudança de schema e todos são
verificáveis pelo mesmo rebuild.

## Problemas identificados

### P1 — `except Exception` genérico mascara bug real e HTML malformado igualmente

`extract_dom_patterns`/`extract_semantic_sections` (`parsing/html_parser.py`)
envolvem toda a travessia BeautifulSoup num único `try/except Exception`,
retornando `[]` e logando `logger.warning("...: %s", exc)` — que descarta o
traceback. Do ponto de vista de quem lê o log, um bug real na nossa própria
lógica de assinatura estrutural (`_structure_signature`) e um HTML
legitimamente sem padrões repetidos são indistinguíveis.

### P2 — `_detect_by_structure` usa `find("</div>")` não-balanceado

`section_extractor.py` localiza o fim de uma seção estrutural com
`window.find("</div>", m.start())` — o primeiro `</div>` encontrado em
qualquer lugar depois do match de padding, não o fechamento correspondente à
tag de abertura. Como o div com padding quase sempre tem filhos aninhados
(`<div style={{padding:24}}><div>...</div><div>...</div></div>`), isso
localiza o fechamento do **primeiro filho**, não do container — a seção é
cortada bem antes do conteúdo real terminar.

### P3 — Spread `...x` resolve contra o primeiro `const x = {` do arquivo inteiro

`_find_const_object_body` (`component_extractor.py`) usa `re.search` (só o
primeiro match) sobre o arquivo inteiro. Um bundle minificado repete nomes
genéricos (`style`, `cardStyle`) como `const` local dentro de mais de um
componente — o spread de um componente pode resolver contra o objeto de um
componente completamente diferente, com confiança total e nenhum sinal de
ambiguidade.

## Solução proposta

| Task | Problema | Camada |
|---|---|---|
| T49 | P1 | `parsing/html_parser.py` |
| T50 | P2 | `extraction/section_extractor.py` |
| T51 | P3 | `extraction/component_extractor.py` |

**T49** — troca `logger.warning("...: %s", exc)` por `logger.exception(...)`
nos dois `except`. Comportamento observável (retorna `[]`) não muda — o que
muda é que o traceback completo fica disponível no log, tornando um bug real
distinguível de "sem padrões" para quem estiver depurando. O `except Exception`
amplo continua sendo intencional (BeautifulSoup nunca pode derrubar o
pipeline por HTML malformado de um protótipo).

**T50** — nova função `_find_balanced_div_end(window, div_start)`, um scanner
de contagem de profundidade sobre `<div`/`</div>` (não JS-string-aware, ao
contrário de `find_matching_delimiter` — HTML não tem semântica de string
literal a pular; contar substring literal é proporcional para essa
heurística estrutural). Substitui o `find()` não-balanceado no único ponto
que o chamava. Fallback preservado: se nenhum fechamento balanceado é
encontrado dentro do limite de scan, cai numa janela fixa a partir do
`div_start` (mesmo espírito do fallback anterior, agora medido a partir do
início do container, não do ponto do match de padding).

**T51** — `_find_const_object_body` ganha parâmetro `near_offset`. Em vez de
sempre pegar `matches[0]`, coleta todas as declarações de `name` no arquivo e
prefere a mais próxima que precede (ou está em) `near_offset` — o chamador
passa `boundary.end` do componente que está resolvendo o spread (não
`boundary.start`: uma declaração local à própria função do componente fica
*depois* do início da função, então usar `boundary.start` excluiria
erroneamente a declaração correta do próprio componente). Sem nenhuma
declaração antes de `near_offset`, cai para a primeira do arquivo — mesmo
comportamento de hoje, preservado como último recurso.

## Cobertura de testes exigida

- **P1/T49**: comportamento observável inalterado — nenhum teste novo de
  resultado, verificado via suíte existente sem regressão.
- **P2/T50**: `test_nested_div_does_not_cut_at_first_child_close` — dois
  `<div>` filhos dentro de um container com padding; o span capturado inclui
  ambos e termina exatamente após o `</div>` do container, não do primeiro
  filho. `test_structural_fallback_captures_full_padded_container` — via
  `_detect_by_structure`, um `<SectionCard />` que só aparece depois de um
  `<div>` filho aninhado continua presente no `jsx_snippet` da seção.
  `test_unbalanced_close_falls_back_to_fixed_window` — sem `</div>` algum,
  cai no fallback de janela fixa sem lançar exceção. Regressão: todos os
  testes existentes de `_detect_by_structure` continuam passando.
- **P3/T51**: `test_ambiguous_shared_name_resolves_against_own_component` —
  `const cardStyle` declarado localmente em `CardA` e em `CardB` (nomes
  idênticos, valores diferentes); cada componente resolve seu próprio spread
  contra sua própria declaração, não a do outro. Regressão: os 3 testes
  existentes de `TestStyleSpreadResolution` (spread simples, precedência
  local, spread não resolvível) continuam passando com `near_offset` default.

Suíte completa (`pytest tests/unit/ -q`) sem regressão e guardrails
(`pytest tests/test_architecture_guardrails.py -q`) intactas; rebuild real
contra `iPede Manager v21.2.html` (DB descartável em `/tmp`) reportado no
`plan.md`.

## Segurança

Nenhuma nova fronteira de I/O — as três tasks continuam operando só sobre
HTML/JS já carregado do arquivo local do protótipo. `_find_balanced_div_end`
tem limite de scan (`JS_FUNCTION_SCAN_LIMIT`, já usado em outros pontos do
projeto) para não escanear sem limite um arquivo adversarialmente grande.

## Fora de escopo

- Reescrever `_detect_by_structure` como parser HTML completo (BeautifulSoup)
  em vez de scanner de texto — a heurística de padding continua sendo texto
  puro; balanceamento de tags é a correção mínima proporcional ao bug.
- Diferenciar tipos de exceção em `html_parser.py` (ex.: `except
  RecursionError` separado) — sem evidência de que algum tipo específico
  precise de tratamento diferente; `logger.exception` já resolve o problema
  real (visibilidade), sem inventar categorização especulativa.
