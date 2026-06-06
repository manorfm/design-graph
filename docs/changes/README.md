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

---

## Changes planejadas (melhorias de eficiência para agentes)

| Change | Título | Status | Tasks | Impacto |
|--------|--------|--------|-------|---------|
| [C07](C07-reader-query-correctness/) | Reader: correção da query transitiva | 🔲 Planned | T17 | Bug — resultado incorreto |
| [C08](C08-component-discovery-tools/) | MCP: tools de descoberta de componentes | 🔲 Planned | T18–T19 | Alto — ferramentas ausentes |
| [C09](C09-style-token-linkage/) | Graph: link token→propriedade de estilo | 🔲 Planned | T20 | Médio — granularidade |
| [C10](C10-css-class-resolution/) | Parsing: resolução de classes CSS | 🔲 Planned | T21 | Alto — 50% estilos perdidos |
| [C11](C11-jsx-completeness/) | Extraction: JSX com rendering condicional | 🔲 Planned | T22 | Médio — contexto dinâmico |

---

## Estrutura de cada change

```
CXX-nome/
  spec.md      ← o QUE e POR QUÊ (contratos, invariantes, exemplos)
  plan.md      ← COMO (sequência TDD, critérios de aceite)
  TXX-*.md     ← tasks individuais (uma por responsabilidade de arquivo)
```
