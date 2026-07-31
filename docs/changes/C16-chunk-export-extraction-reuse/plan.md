# Plan C16 — Chunk export: reusar extração do pipeline

## Objetivo

Eliminar a duplicação entre `cli/build.py` e `pipeline/coordinator.py` que
causava dois bugs reais de divergência, sem regredir `design-graph build`
nem `design-graph chunk`.

## Critério de aceite

```bash
pytest tests/integration/test_cli_end_to_end.py -k TestChunkCommand -v
pytest tests/unit/pipeline/test_coordinator_edge_paths.py -k ScreenComponentSplit -v
pytest tests/test_architecture_guardrails.py -q
pytest tests/unit/ -q   # suíte completa sem regressão
design-graph chunk "iPede Manager v15.1.html" --output /tmp/x.jsonl
# "extract_all_components: extracted N unique components" deve bater com
# o N relatado por `design-graph "iPede Manager v15.1.html"` (build normal)
```

## Sequência TDD

### Fase 1 — reproduzir o bug 2 (seções de tela arrow-declarada)

**RED:** `test_chunk_extracts_sections_for_arrow_declared_screen` contra
`tests/fixtures/arrow_screen.html` (tela `const HomePage = () => (...)`
com 2 seções marcadas por comentário) — o código antigo gerava só 1 chunk
(o chunk de tela, sem nenhuma seção), confirmado rodando o teste contra o
código não modificado.

### Fase 2 — reproduzir o bug 1 (tela extraída como componente)

**RED:** `TestExtractReactScreenComponentSplit` — chamada direta à função
(ainda privada nesse ponto) falha por `ImportError` já que o nome público
`extract_react` ainda não existe.

### Fase 3 — GREEN

Renomear `_extract_react`→`extract_react`,
`_extract_plain_html`→`extract_plain_html` em `coordinator.py` (públicas,
sem mudança de assinatura/comportamento — só visibilidade). Atualizar as
2 chamadas internas do próprio `coordinator.py`. Remover as 2 funções
duplicadas de `cli/build.py`; `_build_and_export_chunks` passa a chamar
`extract_react`/`extract_plain_html` diretamente.

### Fase 4 — validação end-to-end

Build real (`design-graph build`) e chunk real (`design-graph chunk`)
contra `iPede Manager v15.1.html` devem relatar o mesmo número de
componentes extraídos (173, antes 189 no chunk). Contagem de chunks
gerados neste prototype específico não muda (nenhuma tela é arrow-declarada
aqui) — o bug 2 fica coberto pelo fixture dedicado, não pelo prototype
real.

## Nota sobre o guardrail G9

A duplicação existia, em parte, porque o guardrail G9
(`cli/ não importa parsing/extraction/graph diretamente`) documentava uma
exceção pro chunk export "porque não existe caminho do coordinator pra
rodadas só-de-chunk". Essa frase ficou imprecisa depois desta change — a
*extração* agora tem um caminho compartilhado; só carregamento e chunking
continuam sem equivalente no coordinator. Docstring do teste atualizada
pra refletir isso.
