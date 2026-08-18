# T36 — Deduplicação de ícones SVG inline

**Arquivos:** `src/design_graph/core/models.py`, `src/design_graph/core/patterns.py`,
`src/design_graph/extraction/icon_extractor.py` (novo),
`src/design_graph/extraction/component_extractor.py`,
`src/design_graph/graph/schema.py`, `src/design_graph/graph/writer.py`,
`src/design_graph/graph/reader.py`, `src/design_graph/pipeline/coordinator.py`,
`src/design_graph/cli/build.py`
**Depende de:** T35 (C21, proteção de markup cru — este change deduplica o
que aquele passou a preservar)
**Status:** ✅ done

## Responsabilidade

Armazenar cada ícone SVG inline uma única vez no grafo, independente de
quantos componentes o reusam, e devolver o markup completo — nunca uma
referência — sempre que um componente ou tela é de fato consultado (MCP
ou export de chunks).

## Critério de aceite

- `IconAsset` (`core/models.py`) — value object com id determinístico via
  hash de conteúdo (`EntityId.derive`), mesmo padrão de `DesignToken`.
  `resolve_icon_markers` — única função que expande `{[icon:id]}` de
  volta ao markup, reusada por todo consumidor.
- `extract_icons` (`extraction/icon_extractor.py`, novo) — varredura por
  profundidade de `<svg>`/`</svg>` (não regex de cauda), lida
  corretamente com self-closing e sprite com `<svg>` aninhado; tag sem
  fechamento é deixada intocada, nunca corrompida.
- `Icon(id, markup)` no schema (`graph/schema.py`) — sem relação de
  grafo; a referência é o próprio id embutido no marcador.
- `write_icons` (`graph/writer.py`) — dedup na escrita, idêntico em forma
  a `write_tokens`.
- `GraphReader._resolve_icons` — expande marcadores em lote (1 query por
  chamada, não 1 por ícone) nos 6 pontos onde `jsx_snippet` sai do grafo.
  Nenhum consumidor de `GraphReader` (MCP) vê o marcador.
- `pipeline/coordinator.py` — `icons` agregado e deduplicado a partir de
  todos os componentes extraídos, escrito ao lado de `tokens`; propagado
  a `BuildStats`/saída JSON/resumo do CLI.
- Gap real encontrado e fechado: `design-graph chunk` roda extração
  própria sem grafo — corrigido para resolver marcadores com os
  `IconAsset` da mesma passada de extração, reusando `resolve_icon_markers`
  (não uma segunda implementação).
- Suíte completa (`pytest -q`) sem regressão: 1662 passando (1615 + 47
  testes novos), 0 falhas.
- Guardrails de arquitetura intactas (G1/G2/G9) — nenhum import cruzado
  novo em direção proibida.

## Fora de escopo

- `Section.jsx_snippet` — nunca passa por `sanitize_jsx`/`extract_icons`;
  nenhum gap relatado ali.
- `extraction/plain_html_component_extractor.py` (caminho DOM-pattern) —
  SVGs nesse caminho continuam inline, sem dedup; nenhum gap relatado.
- Relação de grafo `USES_ICON` / tool `find_icon_usage` — não pedido; a
  referência inline por id já resolve custo de armazenamento e leitura.
