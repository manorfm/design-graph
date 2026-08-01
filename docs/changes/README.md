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

> C12 cobriu o caso dominante (mutação direta de `style` no handler). C13
> fecha os dois gaps que C12 deixou fora de escopo: handlers com mais de uma
> mutação de estilo, e o padrão `onMouseEnter={() => setHover(true)}` com
> estilo condicional por estado React (`style={{ prop: hover ? A : B }}`).
> C14 é uma mudança de qualidade arquitetural (não de captura de dados) —
> refactor puro, sem alteração de comportamento observável. C15 volta ao
> padrão de C07–C13 (fechar gap real encontrado por análise do prototype).

---

## Estrutura de cada change

```
CXX-nome/
  spec.md      ← o QUE e POR QUÊ (contratos, invariantes, exemplos)
  plan.md      ← COMO (sequência TDD, critérios de aceite)
  TXX-*.md     ← tasks individuais (uma por responsabilidade de arquivo)
```
