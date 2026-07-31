# T30 — Reusar extração do coordinator no chunk export

**Arquivo:** `src/design_graph/pipeline/coordinator.py`, `src/design_graph/cli/build.py`
**Depende de:** T13 (PipelineCoordinator)
**Status:** ✅ done

## Responsabilidade

Eliminar a reimplementação divergente da extração React/plain-HTML em
`cli/build.py` — `design-graph chunk` deve produzir exatamente os mesmos
componentes/telas/seções que `design-graph build` produziria pro mesmo
prototype.

## Critério de aceite

- `_extract_react`/`_extract_plain_html` em `coordinator.py` tornam-se
  públicas (`extract_react`/`extract_plain_html`).
- `cli/build.py` não tem mais `_extract_chunks_react`/
  `_extract_chunks_plain_html` — chama as funções públicas do coordinator
  diretamente.
- Uma tela (`is_screen(name) == True`) nunca aparece na lista de
  componentes extraídos, em nenhum dos dois comandos.
- Seções são extraídas corretamente pra telas declaradas como
  `function Name()` **e** `const Name = () =>`.
- Testes novos: `tests/fixtures/arrow_screen.html`,
  `test_chunk_extracts_sections_for_arrow_declared_screen` (integração),
  `TestExtractReactScreenComponentSplit` (unit, coordinator).
- Suíte completa (`pytest -q`) sem regressão — inclui
  `test_architecture_guardrails.py` (G9).
- Validação real: `design-graph chunk` no prototype de referência relata a
  mesma contagem de componentes que `design-graph build` (173, antes 189).
