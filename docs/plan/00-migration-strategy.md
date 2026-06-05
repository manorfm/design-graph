# Plan 00 — Estratégia de Migração

## Princípio

Migração incremental sem quebrar o sistema existente.
Cada fase entrega valor standalone — ao final de cada fase, `design-graph` funciona.

A estrutura `src/design_graph/` coexiste com os arquivos raiz originais
(`build_graph.py`, `mcp_server.py`, etc.) até a Fase 5, quando os originais
são aposentados.

---

## Fases

| Fase | Entrega | Depende de |
|---|---|---|
| **1 — Parsing** | `src/design_graph/parsing/` + testes unitários | — |
| **2 — Extraction** | `src/design_graph/extraction/` + single-pass + CONTAINS | Fase 1 |
| **3 — Graph** | `src/design_graph/graph/` + schema CONTAINS | Fase 2 |
| **4 — Pipeline** | `src/design_graph/pipeline/coordinator.py` (async) | Fases 1-3 |
| **5 — MCP** | `src/design_graph/mcp/` com search scoring | Fase 3 |
| **6 — Chunker** | `src/design_graph/extraction/chunker.py` + CLI | Fase 2 |
| **7 — Cutover** | Aposentar arquivos raiz, atualizar pyproject.toml | Fases 1-6 |

---

## Regra de cutover

Os arquivos raiz são mantidos **inalterados** até o final da Fase 6.
O cutover da Fase 7 é: atualizar `pyproject.toml` para apontar para os novos
entry points e deletar os arquivos legados.

---

## Compatibilidade de API

O MCP exporta as mesmas tools. Nenhum `doc=` existente quebra.
A nova tool `get_component_children` é aditiva.

O banco de dados `.db` gerado pela nova pipeline **não é compatível** com o
banco gerado pela pipeline antiga (schema novo inclui tabela `CONTAINS`).
Ao instalar a nova versão, o usuário precisa rodar `design-graph --force`
para reconstruir o grafo.

---

## Critério de aceite por fase

| Fase | Critério |
|---|---|
| 1 | `pytest tests/unit/parsing/` verde |
| 2 | `pytest tests/unit/extraction/` verde; single-pass == resultados do legado |
| 3 | `pytest tests/unit/graph/` verde; banco inclui relações CONTAINS |
| 4 | `pytest tests/integration/test_pipeline.py` verde; build é mais rápido |
| 5 | `pytest tests/unit/mcp/` verde; search retorna resultados ordenados por score |
| 6 | `pytest tests/unit/extraction/test_chunker.py` verde; CLI `chunk` funciona |
| 7 | `pytest` completo verde; `design-graph`, `design-mcp`, `design-query` funcionam |

---

## Estrutura de diretórios criada por fase

```
Fase 1:
  src/design_graph/__init__.py
  src/design_graph/core/{models,patterns,constants}.py
  src/design_graph/parsing/{source_loader,format_detector,js_parser,html_parser,token_extractor}.py
  tests/unit/parsing/test_*.py

Fase 2:
  src/design_graph/extraction/{component_extractor,screen_extractor,section_extractor}.py
  tests/unit/extraction/test_{component,screen,section}_extractor.py

Fase 3:
  src/design_graph/graph/{schema,writer,reader,diff}.py
  tests/unit/graph/test_{schema,writer,reader,diff}.py

Fase 4:
  src/design_graph/pipeline/{coordinator,state}.py
  tests/integration/test_pipeline.py

Fase 5:
  src/design_graph/mcp/{server,tools,search,aliases}.py
  tests/unit/mcp/test_{tools,search}.py
  tests/integration/test_mcp_e2e.py

Fase 6:
  src/design_graph/extraction/chunker.py
  src/design_graph/cli/{build,query}.py  (atualizado com cmd_chunk)
  tests/unit/extraction/test_chunker.py
  tests/fixtures/{plain.html,large_bundle.html}

Fase 7:
  pyproject.toml (entry points atualizados)
  DELETED: build_graph.py, mcp_server.py, extract_design_system.py, query.py
```

---

## Dependências externas novas

Nenhuma. O projeto continua com apenas `beautifulsoup4` e `kuzu`.
`asyncio` e `dataclasses` são stdlib Python 3.9+.

---

## Risco principal

**Kuzu versão**: a sintaxe do schema (especialmente `CONTAINS` com propriedade)
foi testada contra Kuzu >= 0.6. Verificar `kuzu.__version__` no início do build
e emitir aviso se < 0.6.

```python
# pipeline/coordinator.py
import kuzu
_KUZU_MIN = (0, 6)
_ver = tuple(int(x) for x in kuzu.__version__.split(".")[:2])
if _ver < _KUZU_MIN:
    sys.stderr.write(
        f"[design-graph] AVISO: Kuzu {kuzu.__version__} detectado; "
        f">= 0.6 recomendado para suporte a CONTAINS com propriedades.\n"
    )
```
