# Spec C16 — Chunk export: reusar a extração do pipeline principal

## Problema

`cli/build.py` tinha duas funções privadas (`_extract_chunks_react`,
`_extract_chunks_plain_html`) que **reimplementavam**, de forma
independente e divergente, a mesma lógica de extração já existente em
`pipeline/coordinator.py` (`_extract_react`/`_extract_plain_html`, usadas
pelo `design-graph build` principal). Achado ao investigar uma
discrepância real: `design-graph chunk` reportava **189** componentes
extraídos contra **173** no `design-graph build` do mesmo prototype.

Duas divergências reais entre as duas implementações:

1. **Telas contadas como componentes.** O pipeline principal separa
   `visual_bounds` em `screen_bounds`/`comp_bounds` antes de chamar
   `extract_all_components` — uma tela nunca é extraída como se fosse um
   componente reutilizável. A versão duplicada em `cli/build.py` não fazia
   essa separação: passava `all_bounds` inteiro (telas incluídas) pra
   `extract_all_components`. Sem efeito diretamente visível nos chunks
   exportados neste prototype (nenhuma tela era referenciada como
   `component_ref` por outra tela/seção), mas representava trabalho
   desperdiçado e um risco real caso isso mudasse.

2. **Seções de telas declaradas como arrow function nunca eram
   extraídas.** A versão duplicada localizava o boundary de cada tela via
   `find_function_boundaries(js, RE_SCREEN_FN)` — `RE_SCREEN_FN` exige a
   palavra-chave literal `function`, então uma tela declarada
   `const HomePage = () => (...)` nunca era encontrada, e suas seções
   (marcadas por comentários JSX) desapareciam silenciosamente do export
   `.jsonl`. O pipeline principal usa `is_screen()` (classificação por
   nome, funciona pra qualquer forma de declaração — já corrigido pra
   arrow functions no C13) — não tinha esse bug.

## Impacto medido

No prototype `iPede Manager v15.1.html`: `extract_all_components` relatava
189 componentes via `design-graph chunk` contra 173 via `design-graph
build` — 16 telas contadas em duplicidade. Corrigido: ambos os comandos
agora relatam exatamente 173.

## Solução

`_extract_react`/`_extract_plain_html` em `pipeline/coordinator.py`
tornam-se públicas (`extract_react`/`extract_plain_html`) — deixam de ser
detalhe interno de um módulo pra ser a única implementação de extração,
compartilhada pelos dois consumidores (`run_pipeline` e
`_build_and_export_chunks`). As duas funções duplicadas em `cli/build.py`
são removidas inteiramente (~65 linhas), substituídas por uma chamada
direta às versões públicas do coordinator.

Isso também torna a exceção documentada no guardrail G9
(`test_architecture_guardrails.py`) mais precisa: antes dizia "não existe
caminho do coordinator pra rodadas só-de-chunk"; agora a extração em si
passa pelo coordinator — só carregamento (`source_loader`) e chunking
(`chunker`) continuam sem equivalente no coordinator (que sempre escreve
num grafo Kuzu, não tem modo "só extrai e devolve").

## Invariantes

- `extract_react`/`extract_plain_html` produzem exatamente o mesmo
  resultado pros dois chamadores — mesma função, mesmo comportamento, sem
  possibilidade de divergência futura.
- Uma tela nunca aparece em `[c.name for c in extracted_comps]`.
- Seções de uma tela são extraídas independentemente da forma de
  declaração (`function Name()` ou `const Name = () =>`).

## Arquivos afetados

| Arquivo | Mudança |
|---|---|
| `src/design_graph/pipeline/coordinator.py` | `_extract_react`→`extract_react`, `_extract_plain_html`→`extract_plain_html` (públicas) |
| `src/design_graph/cli/build.py` | remove `_extract_chunks_react`/`_extract_chunks_plain_html`; `_build_and_export_chunks` chama as funções públicas do coordinator |
| `tests/fixtures/arrow_screen.html` (novo) | tela declarada como arrow function, com 2 seções |
| `tests/integration/test_cli_end_to_end.py` | `test_chunk_extracts_sections_for_arrow_declared_screen` |
| `tests/unit/pipeline/test_coordinator_edge_paths.py` | `TestExtractReactScreenComponentSplit` |
| `tests/test_architecture_guardrails.py` | docstring do G9 atualizada |
