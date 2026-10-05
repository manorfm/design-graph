# Spec 00 — Visão Geral do Sistema

## Propósito

`design-graph` converte um arquivo HTML de protótipo em um grafo de conhecimento (Kuzu) e
expõe esse grafo via servidor MCP para que agentes de IA possam consultar componentes, tokens
de design e hierarquias de telas de forma cirúrgica, sem injetar o HTML inteiro no contexto.

## Problemas que esta revisão resolve

| # | Problema atual | Impacto |
|---|---|---|
| P1 | `build_graph.py` percorre o mesmo JS 5× por componente | CPU e tempo de build 5× maiores que o necessário |
| P2 | Janelas fixas de 14000 chars truncam componentes grandes silenciosamente | Dados incompletos no grafo |
| P3 | `_capture_return_block` usa contagem de parênteses, não de chaves | Falha em funções com parênteses aninhados |
| P4 | Hierarquia Component→CONTAINS→Component ausente | Queries de composição são impossíveis |
| P5 | Seções só detectadas via comentários JSX específicos | Protótipos sem comentários ficam sem granularidade |
| P6 | Busca MCP usa `CONTAINS` literal sem ranking | Resultados irrelevantes antes dos relevantes |
| P7 | HTML genérico (plain HTML) tem suporte superficial | CSS-class heurístico, não detecta padrões DOM |
| P8 | Sem suporte a chunking de HTML para contexto de IA | Arquivo grande gerado por agente não é processável |
| P9 | Três "god files" com responsabilidades misturadas | Dificulta teste, manutenção e extensão |

## Escopo desta revisão

**Inclui:**
- Reestruturação em módulos com responsabilidade única
- Single-pass extractor por componente
- Detecção real de limite de função (contagem de chaves)
- Relação `CONTAINS` no grafo de componentes
- Fallback de seções por estrutura visual
- Busca com score de relevância
- Suporte a HTML genérico (detecção de padrões DOM repetidos)
- Chunker de HTML para contexto de IA
- Pipeline assíncrono com coroutines (extração de componentes em paralelo)
- TDD completo com guardrails

**Não inclui:**
- Parser AST completo (acorn/esprima/tree-sitter) — complexidade não justificada neste ciclo
- Suporte a arquivos CSS/SCSS isolados
- Renderização headless para análise visual
- UI web

## Arquitetura proposta

```
design-graph/
├── src/
│   └── design_graph/
│       ├── capture/                 # formato do protótipo → entidades do modelo (plugável)
│       │   ├── base.py              # protocolo Capture
│       │   ├── registry.py          # escolhe a captura pelo conteúdo do arquivo
│       │   ├── markup.py            # texto visível de markup (comum às capturas)
│       │   ├── html_prototype/      # React empacotado, Tailwind e HTML puro
│       │   │   ├── patterns.py      # todos os RE_* da captura
│       │   │   ├── constants.py
│       │   │   ├── parsing/         # HTML → dados brutos (source_loader, js_parser, token_extractor…)
│       │   │   └── extraction/      # dados brutos → entidades (component, screen, section extractors…)
│       │   └── dc_canvas/           # canvas DC (páginas, blocos, componentes inferidos)
│       ├── model/                   # modelo estável, sem dependências de captura ou interface
│       │   ├── entities.py          # entidades e value objects (Component, Screen, Section, Token…)
│       │   └── graph/               # Kuzu: schema, writer, reader, diff, catalog
│       ├── pipeline/                # orquestração assíncrona (coordinator, state)
│       └── interface/               # interfaces finas sobre o reader
│           ├── cli/                 # design-graph, design-query, chunk export
│           └── mcp/                 # servidor MCP: tools.py (dispatcher) + *_tools.py, search, aliases
├── tests/
│   ├── conftest.py
│   ├── fixtures/                    # protótipos sintéticos (simple, plain, large_bundle…)
│   ├── support/                     # geradores de fixture (ex.: canvas DC)
│   ├── test_architecture_guardrails.py
│   ├── unit/                        # espelha src/: capture/, model/, pipeline/, interface/
│   └── integration/                 # pipeline, CLI e MCP de ponta a ponta
├── docs/
│   ├── spec/       ← este diretório
│   ├── plan/
│   ├── tasks/
│   └── changes/
└── pyproject.toml
```

## Entry points (CLI)

| Comando | Módulo | Função |
|---|---|---|
| `design-graph <proto.html>` | `design_graph.interface.cli.build` | `main()` |
| `design-mcp` | `design_graph.interface.mcp.server` | `main()` |
| `design-query <cmd>` | `design_graph.interface.cli.query` | `main()` |

## Invariantes do sistema

1. **Leitura imutável**: nenhum módulo de captura (`parsing/`, `extraction/`) modifica o string `js` ou `html`.
   Toda extração retorna novos objetos. Isso é o que torna a paralelização segura.

2. **Escrita serializada**: todas as escritas no Kuzu acontecem na fase final, de forma
   sequencial, a partir dos dados já extraídos. Kuzu não suporta writes concorrentes.

3. **Idempotência de nós**: antes de criar qualquer nó, verificar se já existe. Usar `MERGE`
   ou verificação prévia para evitar duplicatas no grafo.

4. **Hash como cache**: o build é pulado se `html_hash` não mudou. O `--force` ignora o hash.

5. **Falha silenciosa apenas em inserções**: a função `safe()` absorve erros de inserção
   duplicada no Kuzu. Erros de leitura/parsing propagam normalmente.

## Glossário

| Termo | Definição |
|---|---|
| Screen | Componente React que representa uma tela (nome termina em Page/Screen/Dashboard/etc.) |
| Component | Qualquer função React PascalCase que não é Screen |
| Section | Bloco visual nomeado dentro de uma Screen (detectado por comentário ou estrutura) |
| Token | Valor de design reutilizável: cor, espaçamento, sombra, etc. |
| Chunk | Fragmento de HTML/JSX com metadados de contexto, pronto para consumo por IA |
| JSX snippet | Trecho do `return()` de um componente, sanitizado (lógica removida, estrutura mantida) |
| Bundle | JS minificado/comprimido embedado em `<script>` tags do HTML do protótipo |
| Graph | Banco de dados Kuzu com nós e arestas representando o design system |
| MCP | Model Context Protocol — protocolo JSON-RPC 2.0 via stdio |

## Referências

- Spec 01: Módulo `capture/html_prototype/parsing/`
- Spec 02: Módulo `capture/html_prototype/extraction/`
- Spec 03: Módulo `model/graph/`
- Spec 04: Módulo `interface/mcp/`
- Spec 05: Módulo `interface/cli/chunk_export.py`
- Spec 06: Design de concorrência do `pipeline/coordinator.py`
