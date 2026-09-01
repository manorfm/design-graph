# design-graph — Changes Index

Cada change agrupa a spec, o plano de implementação e as tasks da mudança.
C01–C06 cobrem a construção original do sistema. C07–C11 cobrem as melhorias
levantadas após análise de eficiência para uso por agentes de IA.

---

## Visão geral do sistema

- [Spec 00 — Overview](../spec/00-overview.md)
- [Plan 00 — Estratégia de migração](../plan/00-migration-strategy.md)
- [Backlog geral](../tasks/backlog.md)

---

## Changes implementadas

| Change | Título | Status | Tasks |
|--------|--------|--------|-------|
| [C01](C01-core-parsing/) | Core + Parsing | ✅ Done | T01–T05 |
| [C02](C02-component-extraction/) | Extraction (single-pass, CONTAINS) | ✅ Done | T06–T08 |
| [C03](C03-graph-layer/) | Graph Layer (schema, writer, reader, diff) | ✅ Done | T09–T12 |
| [C04](C04-pipeline-mcp/) | Pipeline + MCP Server | ✅ Done | T13–T15 |
| [C05](C05-chunker/) | Chunker + CLI | ✅ Done | T16 |
| [C06](C06-concurrency/) | Concurrency Design | ✅ Done | — |
| [C07](C07-reader-query-correctness/) | Reader: correção da query transitiva | ✅ Done | T17 |
| [C08](C08-component-discovery-tools/) | MCP: tools de descoberta de componentes | ✅ Done | T18–T19 |
| [C09](C09-style-token-linkage/) | Graph: link token→propriedade de estilo | ✅ Done | T20 |
| [C10](C10-css-class-resolution/) | Parsing: resolução de classes CSS | ✅ Done | T21 |
| [C11](C11-jsx-completeness/) | Extraction: JSX com rendering condicional | ✅ Done | T22 |

> C07–C11 foram implementados sem atualização desta tabela; status corrigido em
> 2026-07-30 após auditoria de código (verificação linha a linha contra cada spec).

---

## Changes planejadas (melhorias de eficiência para agentes)

| Change | Título | Status | Tasks | Impacto |
|--------|--------|--------|-------|---------|
| [C12](C12-stateful-interactions/) | Extraction: interações via estilo imperativo (hover/focus sem literal) | ✅ Done | T23 | Alto — Interactions 10→39 no prototype de referência |
| [C13](C13-interaction-capture-completeness/) | Extraction: handlers multi-mutação + correlação estado→ternária + nomes com dígito | ✅ Done | T24–T26 | Alto — Interactions 39→64; 8 componentes/telas versionados (`*V6`/`*V7`) antes invisíveis |
| [C14](C14-domain-model-value-objects/) | Domain model: EntityId, enums, PropDefault, entidades ricas | ✅ Done | T27, T29 | Qualidade — elimina 9 duplicações de geração de id + 4 bugs de drift; refactor puro (stats idênticos ao baseline) |
| [C15](C15-tooltip-text-classification/) | Extraction: classificação de texto de tooltip (title/aria-label/alt) | ✅ Done | T28 | Médio — 143 valores de `title` antes indistinguíveis de conteúdo visível no prototype de referência |
| [C16](C16-chunk-export-extraction-reuse/) | Pipeline: chunk export reusa extração do coordinator | ✅ Done | T30 | Alto — 2 bugs reais: telas contadas como componente (189→173) e seções de telas arrow-declaradas nunca extraídas |
| [C17](C17-screen-detection-and-strenum-consolidation/) | Core: remove regexes de tela mortas + consolida StrEnum | ✅ Done | T31 | Qualidade — elimina código morto com docstring incorreta + 4 redefinições independentes de `(str, Enum)` |
| [C18](C18-mcp-token-efficiency/) | MCP: eficiência de token — fecha CONTAINS, corrige inconsistência, dedup de estilo, remove duplicação | ✅ Done | T32 | Alto — get_screen_full 11→21 componentes numa chamada (InventoryPage); elimina resposta divergente entre tools pro mesmo componente |
| [C19](C19-jsx-variant-disambiguation/) | Extraction: rotula qual variante de JSX concatenada realmente executa | ✅ Done | T33 | Médio — fecha o gap adiado em C18; `Btn`/`Modal` do prototype real confirmados com rótulo correto |
| [C20](C20-search-and-impact-correctness/) | MCP: busca sem cobertura de UIText + impacto de token subestimado | ✅ Done | T34 | Crítico — busca não indexava 1369 nós de texto, contradizendo a própria descrição da tool |
| [C21](C21-jsx-marker-balanced-collapse/) | Extraction: colapso balanceado de expressões dinâmicas em JSX | ✅ Done | T35 | Crítico — marcador `{[conditional:X]}` saía corrompido com prop de chave aninhada (`color={C.red}`); markup cru (ícones) perdido silenciosamente acima de 300 chars |
| [C22](C22-icon-deduplication/) | Graph: deduplicação de ícones SVG inline em tabela endereçável por conteúdo | ✅ Done | T36 | Médio — N cópias do mesmo ícone (uma por componente que o usa) viram 1 nó `Icon`; JSX completo continua saindo em toda leitura via MCP e no export de chunks |

> C12 cobriu o caso dominante (mutação direta de `style` no handler). C13
> fecha os dois gaps que C12 deixou fora de escopo: handlers com mais de uma
> mutação de estilo, e o padrão `onMouseEnter={() => setHover(true)}` com
> estilo condicional por estado React (`style={{ prop: hover ? A : B }}`).
> C14 é uma mudança de qualidade arquitetural (não de captura de dados) —
> refactor puro, sem alteração de comportamento observável. C15 volta ao
> padrão de C07–C13 (fechar gap real encontrado por análise do prototype).

---

## Changes de auditoria e correção (C23–C35)

| Change | Título | Status | Tasks | Impacto |
|--------|--------|--------|-------|---------|
| [C23](C23-agent-context-fidelity/) | Fidelidade de contexto do MCP para agentes de IA | ✅ Done | T37–T43 | Fecha gaps encontrados numa auditoria real de sessão de agente (ver `audit/mcp-gap-analysis-item-basic-tab.md`) |
| [C24](C24-css-style-resolution-completeness/) | Completude da resolução de estilo (CSS embutido + spread) | ✅ Done | T44–T46 | Extrai `<style>` embutido no `inner_html` do bundle + resolve spreads (`...base, override`) |
| [C25](C25-write-integrity/) | Integridade de escrita (lock de build + erros de escrita visíveis) | ✅ Done | T47–T48 | Evita builds concorrentes corromperem a mesma DB; erros de escrita deixam de ser engolidos |
| [C26](C26-parsing-correctness/) | Correções de bugs de parsing (except genérico, div não-balanceado, spread ambíguo) | ✅ Done | T49–T51 | Três bugs de parsing corrigidos após revisão linha a linha |
| [C27](C27-reader-mcp-quick-wins/) | Reader/MCP: ganhos rápidos | ✅ Done | T52–T55 | Melhorias pontuais de ergonomia de leitura via MCP |
| [C28](C28-truncation-as-data/) | Truncamento como dado, não log | ✅ Done | T56–T60 | `truncated_fields` vira campo estruturado no grafo em vez de só aparecer em log — agente consegue detectar truncamento sem grep de log |
| [C29](C29-hover-focus-states/) | Estados hover/focus completos (Tailwind + correção de pareamento) | ✅ Done | T61–T62 | `StyleState` ganha resolução de prefixo `hover:`/`focus:`; corrige bug de pareamento `enter`/`leave` via `zip()` |
| [C30](C30-render-order/) | Ordem de renderização (`order_index`) | ✅ Done | T63–T66 | `child_refs`/`component_refs` preservam ordem real de aparição no JSX em vez de alfabetizar |
| [C31](C31-mcp-api-expansion/) | Expansão da API MCP (`get_component_full`, paginação, `get_build_diff`) | ✅ Done | T67–T69 | Novas tools de leitura para reduzir round-trips do agente |
| [C32](C32-library-icons/) | Referências externas permanentemente não resolvidas (re-escopado de "ícones de biblioteca") | ✅ Done | T70 | Evita `Component` fantasma para nomes que nunca resolvem (ícones de biblioteca externa) |
| [C33](C33-round-trip-validation/) | Validação round-trip (spike + implementação) | ✅ Done | T71 | `design-graph validate` confirma que o grafo reflete o HTML de origem sem perda silenciosa |
| [C34](C34-post-audit-fixes/) | Correções de uma segunda rodada de auditoria (C25–C33) | ✅ Done | T72–T76 | 5 bugs achados numa segunda auditoria crítica do código de C25–C33, dois deles críticos (reordenação alfabética desfazendo C30; `Component` fantasma com nome de `Screen`) |
| [C35](C35-media-query-css-scoping/) | Parsing: `@media` corrompe a resolução de classe CSS | ✅ Done | T77–T79 | Crítico — `extract_css_rules`/`extract_tag_pseudo_rules` absorviam regras de dentro de `@media` como se fossem incondicionais, sobrescrevendo o valor default real (evidência: `.page-title` em `toToggle v2.2.html` perdia 2 de 3 propriedades e retornava o valor de viewport ≤600px como se fosse o padrão). T77 corrige a corrupção; T78 expõe as regras responsivas separadamente — nova coluna `media` em `Style`, seção "Estilos responsivos" em `get_component_spec`, descrição da tool atualizada para o agente saber que ela existe. T79 (descoberto ao exercitar `get_component_full` contra o grafo real, não por revisão especulativa) fecha 6 outras tools (`get_component`, `get_component_full`, `get_styles_with_tokens`, `get_screen_full`, `get_component_layout_profile`, `get_screen_layout`) que o próprio T78 tinha reaberto para a mesma classe de bug de P1, um nível acima |
| [C36](C36-mcp-style-attribution-and-discoverability/) | MCP: atribuição de estilo por seletor + descoberta de classe CSS compartilhada | ✅ Done | T80–T84 | Crítico — relato externo (`toToggle`, seção "Audit item") verificado contra o grafo real: `get_section`/`get_screen_full` achatavam estilos de seletores diferentes num único array (`.audit-item`/`.audit-rail`/`.audit-dot` misturados); `GraphWriter` pulava a edge `HAS_STYLE`/`SECTION_HAS_STYLE` (não só o nó) para qualquer classe CSS compartilhada por ≥2 donos; `get_full_jsx("App")` devolvia só o primeiro `return` de um componente com guard clauses, descartando o branch que renderiza a UI principal; `get_screen_layout` nunca cobria `Section`; classes CSS sem componente React nomeado (`page-title`, `chip`) eram invisíveis a `search`/`get_component_spec`. T80 corrige múltiplos `return` (parsing); T81 corrige atribuição por seletor + a edge perdida (fundação); T82 adiciona `get_full_styles` (escape hatch, sem truncamento); T83 estende `get_screen_layout` a seções; T84 adiciona `find_styles_by_class`/`find_class_owners`/`list_shared_style_classes` |

> C23 nasceu de uma investigação real de sessão de agente, não de análise de
> código a priori — mesmo padrão de origem do C35 e do C36. C34 é uma
> segunda rodada de auditoria sobre C25–C33, não um change de feature. C35 e
> C36 são o mesmo tipo de achado: relato externo verificado contra o código
> e transformado em bug real (C35: "design-graph não expõe media queries";
> C36: "estilos de HistoryView vêm misturados e classes compartilhadas
> nunca são encontradas").

---

## Estrutura de cada change

```
CXX-nome/
  spec.md      ← o QUE e POR QUÊ (contratos, invariantes, exemplos)
  plan.md      ← COMO (sequência TDD, critérios de aceite)
  TXX-*.md     ← tasks individuais (uma por responsabilidade de arquivo)
```
