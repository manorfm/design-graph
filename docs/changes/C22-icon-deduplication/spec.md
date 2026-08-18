# Spec C22 — Deduplicação de ícones SVG inline

## Problema

Perguntado pelo usuário: ícones em SVG inline (`<svg>...</svg>`) aparecem
em vários componentes de um mesmo prototype — o mesmo ícone de check,
seta, fechar etc. se repete dezenas de vezes. Antes deste change, cada
ocorrência era persistida por extenso dentro do `jsx_snippet` do
componente que a contém (protegido de colapso pelo mecanismo do C21,
já que markup cru sem nome de componente PascalCase é a única cópia da
sua forma visual). Sem deduplicação, um ícone reusado em N componentes
custava N cópias do mesmo texto no grafo — e N vezes o custo de tokens
para quem consulta via MCP.

## Solução

Tabela de conteúdo endereçável, no mesmo padrão já usado por `Token`
(`core/models.DesignToken` + `graph/writer.write_tokens`): o SVG é
extraído uma vez, tem seu id derivado de um hash do próprio markup
(`EntityId.derive`, igual a `Token`/`Style`), e é armazenado uma única
vez independente de quantos componentes o referenciam.

- `core/models.py`: `IconAsset` (frozen dataclass) — `id` + `markup`.
  `IconAsset.create(markup)` deriva o id via hash de conteúdo; `__str__`
  produz o marcador textual `{[icon:id]}`, no mesmo estilo de
  `JsxMarker` (`{[conditional:X]}` etc., do C21). `resolve_icon_markers(text,
  markup_by_id)` é a operação inversa — expande marcadores de volta ao
  markup completo — e vive aqui (não em `graph/` nem `extraction/`) porque
  os dois lados que precisam decodificar o marcador (`GraphReader`, e o
  exportador de chunks que nunca passa pelo grafo) dependem de `core/`,
  não um do outro.
- `extraction/icon_extractor.py` (novo): `extract_icons(jsx)` varre o JSX
  bruto de um componente, localiza blocos `<svg>...</svg>` (ou
  self-closing) por contagem de profundidade — não por regex de cauda —
  para não fechar cedo demais num sprite com `<svg>` aninhado
  (`<defs><svg>...</svg></defs>`), e substitui cada bloco pelo marcador.
  Roda **antes** de `sanitize_jsx`, então o mecanismo de proteção de
  markup cru do C21 nunca mais precisa lidar com o SVG em si — só com o
  marcador curto, que sempre sobrevive por já ter menos de 300 caracteres.
- `graph/schema.py`: nó `Icon(id, markup)`. Sem relação `USES_ICON` — a
  referência já está embutida no próprio texto do marcador (`icon_xxxxxxxx`),
  então resolver é um lookup direto por id, não uma travessia de grafo.
- `graph/writer.py`: `write_icons(icons)`, cópia estrutural de
  `write_tokens` — dedup na escrita via `_inserted_icon_ids`.
- `graph/reader.py`: `_resolve_icons(jsx_snippet)` expande os marcadores
  de volta ao SVG completo com uma única query em lote
  (`MATCH (i:Icon) WHERE i.id IN $ids`), chamada nos 6 pontos onde
  `jsx_snippet` sai do grafo (`get_component`, `get_component_spec`,
  `get_section`, `get_full_jsx`, e as duas listas de `get_screen_full`).
  Quem consome `GraphReader` (MCP `mcp/tools.py`) nunca vê o marcador —
  só o SVG completo, exatamente como via antes deste change.

## Gap encontrado durante a implementação

`design-graph chunk` (exportação de JSONL) roda sua própria passada de
extração em memória, independente do grafo (`cli/build._build_and_export_chunks`
chama `coordinator.extract_react`/`extract_plain_html` diretamente — não
há grafo para consultar `Icon` contra). Sem correção, o marcador
`{[icon:id]}` vazaria sem nunca ser expandido nos chunks exportados —
uma regressão real, pega pelo teste de integração
`test_chunk_expands_icon_markers_to_full_svg` antes de qualquer commit.
Corrigido resolvendo os marcadores ali com os próprios `IconAsset`
que a mesma passada de extração acabou de produzir, via a mesma
`resolve_icon_markers` — não uma segunda implementação da substituição.

## O que foi deliberadamente deixado de fora

- `Section.jsx_snippet` — nunca passou por `sanitize_jsx` (é um slice
  bruto do bloco HTML, truncado em 2-3k chars, usado como preview), então
  nunca continha SVG protegido para começar. Estender a extração de ícone
  para lá dobraria a superfície do change sem um gap real identificado.
- `extraction/plain_html_component_extractor.py` (caminho DOM-pattern,
  prototypes sem JSX/React) — não passa pelo `sanitize_jsx`/`extract_icons`
  de `component_extractor.py`; SVGs nesse caminho continuam inline, sem
  dedup. Mesma justificativa: nenhum gap relatado nesse caminho.
- Relação de grafo `USES_ICON` / tool `find_icon_usage` (paralelo a
  `find_token_usage`) — não pedido; a referência inline já resolve o
  problema de custo de armazenamento e de leitura sem precisar de
  travessia de grafo.

## Invariantes

- O mesmo markup de ícone, usado em qualquer número de componentes,
  gera exatamente um nó `Icon` no grafo (id determinístico por hash de
  conteúdo).
- Nenhum consumidor de `jsx_snippet` fora de `graph/writer.py` (que grava)
  jamais vê o marcador `{[icon:id]}` sem resolução — `GraphReader` resolve
  na leitura; o exportador de chunks resolve na própria passada de
  extração, já que não tem grafo para consultar.
- Um marcador sem `Icon` correspondente (não deveria acontecer contra um
  grafo construído por este mesmo código) é deixado como está, nunca
  apagado silenciosamente — mesma filosofia do C21 para markup cru.
- Componentes sem nenhum `<svg>` não pagam custo algum: `extract_icons`
  retorna o texto original sem alocação extra quando não há span de SVG.
