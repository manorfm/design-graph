# Plan C22 — Deduplicação de ícones SVG inline

## Objetivo

Parar de pagar N cópias do mesmo SVG inline quando N componentes usam o
mesmo ícone — nem no grafo persistido, nem nas respostas MCP — sem perder
o detalhe visual completo quando um componente ou tela é de fato
consultado.

## Critério de aceite

```bash
pytest tests/unit/core/test_models.py -k Icon -v
pytest tests/unit/extraction/test_icon_extractor.py -v
pytest tests/unit/extraction/test_component_extractor.py -k svg_icon -v
pytest tests/unit/graph/test_schema_and_diff.py -k creates_all_node -v
pytest tests/unit/graph/test_writer_reader.py -k Icon -v
pytest tests/integration/test_icon_deduplication_pipeline.py -v
pytest tests/integration/test_cli_end_to_end.py -k icon_markers -v
pytest -q   # suíte completa sem regressão
```

## Sequência TDD

### Fase 0 — desenho

Mapeado o padrão já existente para `DesignToken`/`Style` (id determinístico
via `EntityId.derive`, dedup na escrita via `_inserted_*_ids`,
`GraphWriteSession`/`GraphWriter`) para reaproveitar em vez de inventar um
mecanismo novo. Decisão de design chave: a referência ao ícone fica
embutida como texto (`{[icon:id]}`) dentro do próprio `jsx_snippet`, não
como aresta de grafo — resolver é um lookup por id, não uma travessia,
então nenhuma relação `USES_ICON` é necessária.

### Fase 1 — RED → GREEN, por camada (de baixo para cima)

1. `core/models.py` — `IconAsset` (value object) + merge em
   `ExtractedComponent.consolidate`. Testes em `test_models.py`
   (`TestIconAssetCreate`, `TestExtractedComponentConsolidateMergesIcons`)
   escritos e vermelhos (`ImportError`) antes da classe existir.
2. `core/patterns.py` — `RE_SVG_OPEN_TAG`/`RE_SVG_CLOSE_TAG`/`RE_ICON_MARKER`,
   centralizadas junto das demais regex de JSX (convenção do módulo).
3. `extraction/icon_extractor.py` (novo) — `extract_icons(jsx)` com
   varredura por profundidade (`_iter_svg_spans`), não regex de cauda —
   mesmo raciocínio do C21 para não fechar cedo/tarde demais. Testes em
   `test_icon_extractor.py`: sem SVG, bloco único, self-closing,
   deduplicação (mesmo ícone 2x → 1 asset, 2 marcadores), ícones
   diferentes, sprite com `<svg>` aninhado, tag não fechada (deixada
   intocada).
4. `extraction/component_extractor.py` — `extract_icons` chamado antes de
   `sanitize_jsx`; `icons=icons` no `ExtractedComponent` retornado. Teste
   de integração em `test_component_extractor.py`
   (`test_svg_icon_is_deduplicated_into_marker`).
5. `graph/schema.py` — nó `Icon(id, markup)` + `STATS_QUERIES["icons"]`.
   Teste: `Icon` adicionado à lista de `test_creates_all_node_tables`.
6. `graph/writer.py` — `write_icons`, cópia estrutural de `write_tokens`.
   Testes em `test_writer_reader.py::TestWriteIcons` (inserção, idempotência,
   duplicata no mesmo batch) — mesmo roteiro de `TestWriteTokens`.
7. `pipeline/coordinator.py` — agrega `icons` a partir de
   `comp.icons` de todos os componentes extraídos (dedup por id, um
   dict-comprehension, sem função nova — mesmo estilo já usado para
   `comp_counter`), chama `writer.write_icons(icons)` ao lado de
   `write_tokens`, propaga para `BuildStats`/JSON/print do CLI.
8. `graph/reader.py` — `_resolve_icons(jsx_snippet)`, chamado nos 6 pontos
   de leitura de `jsx_snippet`. Teste de integração ponta-a-ponta em
   `tests/integration/test_icon_deduplication_pipeline.py`: pipeline real
   (`run_pipeline`) com 2 componentes usando o mesmo ícone → 1 nó `Icon`
   no grafo, `get_component`/`get_full_jsx` devolvem o SVG completo, sem
   marcador vazando.

### Fase 2 — gap encontrado e fechado

Ao rodar a suíte de integração completa, revisão manual de todo consumidor
de `jsx_snippet` (`grep -rl jsx_snippet src/`) encontrou
`cli/build._build_and_export_chunks`: roda extração própria, nunca passa
pelo grafo, logo nunca passaria pelo `GraphReader._resolve_icons`. Teste
vermelho escrito primeiro
(`test_cli_end_to_end.py::test_chunk_expands_icon_markers_to_full_svg`,
falhou mostrando o marcador cru no JSONL exportado) — depois corrigido
resolvendo os marcadores com os `IconAsset` da própria passada de
extração, via `resolve_icon_markers` (mesma função usada por
`GraphReader`, não duplicada).

### Fase 3 — refactor

`resolve_icon_markers` inicialmente estava inline em
`GraphReader._resolve_icons`; movida para `core/models.py` (camada 0,
sem dependência) assim que o segundo consumidor (`chunker`) precisou da
mesma lógica — evita a mesma substituição por regex existir em dois
lugares com o mesmo comportamento.

## Validação end-to-end

Suíte completa (`pytest -q`): 1662 passando, 0 falhas, 0 regressão
(1615 antes deste change + 47 testes novos). Guardrails de arquitetura
(G1/G2/G9) intactas — `extraction/icon_extractor.py` só importa de
`core/`; `graph/reader.py` importa de `core/models` (permitido, G2 só
proíbe o sentido contrário); `cli/build.py` só ganhou um import de
`core/models` no topo (não restrito por G9, que só proíbe
`parsing/`/`extraction/`/`graph/` no nível de módulo).
