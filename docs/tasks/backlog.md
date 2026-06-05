# Backlog — design-graph refactor

## Status

| ID | Título | Fase | Depende de | Status |
|---|---|---|---|---|
| T01 | SourceLoader | 1 | — | `[ ] todo` |
| T02 | FormatDetector | 1 | — | `[ ] todo` |
| T03 | JSParser | 1 | — | `[ ] todo` |
| T04 | TokenExtractor | 1 | — | `[ ] todo` |
| T05 | HTMLParser | 1 | — | `[ ] todo` |
| T06 | ComponentExtractor (single-pass) | 2 | T01 T03 T04 | `[ ] todo` |
| T07 | ScreenExtractor | 2 | T03 | `[ ] todo` |
| T08 | SectionExtractor | 2 | T03 T07 | `[ ] todo` |
| T09 | GraphSchema | 3 | — | `[ ] todo` |
| T10 | GraphWriter | 3 | T06 T07 T08 T09 | `[ ] todo` |
| T11 | GraphReader | 3 | T09 T10 | `[ ] todo` |
| T12 | GraphDiff | 3 | — | `[ ] todo` |
| T13 | PipelineCoordinator | 4 | T01-T12 | `[ ] todo` |
| T14 | MCPSearch + Aliases | 5 | T11 | `[ ] todo` |
| T15 | MCPTools + MCPServer | 5 | T11 T14 | `[ ] todo` |
| T16 | Chunker + CLI chunk | 6 | T06 T07 T08 T05 | `[ ] todo` |

---

## Ordem de implementação recomendada

```
Iteração 1 (Fase 1 — pode ser paralela):
  T02 → T03 → T01 (T01 depende de T02)
  T04 (independente)
  T05 (independente)

Iteração 2 (Fase 2):
  T06 (depende de T01 T03 T04)
  T07 (depende de T03)
  T08 (depende de T03 T07)

Iteração 3 (Fases 3+4):
  T09 (independente)
  T12 (independente)
  T10 (depende T06 T07 T08 T09)
  T11 (depende T09 T10)
  T13 (depende tudo)

Iteração 4 (Fase 5):
  T14 (depende T11)
  T15 (depende T11 T14)

Iteração 5 (Fase 6):
  T16 (depende T06 T07 T08 T05)
```

---

## Estrutura de arquivos criada ao final

```
src/
└── design_graph/
    ├── __init__.py
    ├── core/
    │   ├── __init__.py
    │   ├── models.py
    │   ├── patterns.py
    │   └── constants.py
    ├── parsing/
    │   ├── __init__.py
    │   ├── source_loader.py      T01
    │   ├── format_detector.py    T02
    │   ├── js_parser.py          T03
    │   ├── token_extractor.py    T04
    │   └── html_parser.py        T05
    ├── extraction/
    │   ├── __init__.py
    │   ├── component_extractor.py T06
    │   ├── screen_extractor.py    T07
    │   ├── section_extractor.py   T08
    │   └── chunker.py             T16
    ├── graph/
    │   ├── __init__.py
    │   ├── schema.py   T09
    │   ├── writer.py   T10
    │   ├── reader.py   T11
    │   └── diff.py     T12
    ├── pipeline/
    │   ├── __init__.py
    │   ├── coordinator.py  T13
    │   └── state.py        (helper de T13)
    └── mcp/
        ├── __init__.py
        ├── aliases.py  T14
        ├── search.py   T14
        ├── tools.py    T15
        └── server.py   T15

tests/
├── conftest.py
├── fixtures/
│   ├── simple.html         (existente)
│   ├── plain.html          T16
│   └── large_bundle.html   T16
├── unit/
│   ├── parsing/
│   │   ├── test_source_loader.py   T01
│   │   ├── test_format_detector.py T02
│   │   ├── test_js_parser.py       T03
│   │   ├── test_token_extractor.py T04
│   │   └── test_html_parser.py     T05
│   ├── extraction/
│   │   ├── test_component_extractor.py T06
│   │   ├── test_screen_extractor.py    T07
│   │   ├── test_section_extractor.py   T08
│   │   └── test_chunker.py             T16
│   ├── graph/
│   │   ├── test_schema.py T09
│   │   ├── test_writer.py T10
│   │   ├── test_reader.py T11
│   │   └── test_diff.py   T12
│   └── mcp/
│       ├── test_search.py T14
│       └── test_tools.py  T15
└── integration/
    ├── test_pipeline.py    T13
    └── test_mcp_e2e.py     T15
```

---

## Guardrails globais (valem para todas as tasks)

| # | Guardrail | Como verificar |
|---|---|---|
| G1 | Nenhum módulo de `parsing/` importa de `extraction/`, `graph/`, ou `mcp/` | `grep -r "from design_graph.extraction" src/design_graph/parsing/` → vazio |
| G2 | Nenhum módulo de `extraction/` importa de `graph/` ou `mcp/` | Similar |
| G3 | `reader.py` nunca chama `CREATE`/`DELETE`/`MERGE` | `grep -n "CREATE\|DELETE\|MERGE" src/design_graph/graph/reader.py` → vazio |
| G4 | Extractors são funções puras (síncronas) — `async` só no coordinator | `grep -n "async def" src/design_graph/extraction/` → só em `extract_all_components` |
| G5 | Kuzu abre em modo `read_only=True` no reader | Verificar no reader.py |
| G6 | `FunctionBoundary` boundaries não se solapam | `test_boundaries_do_not_overlap` em T03 |
| G7 | `chunk_id` só contém `[a-z0-9_]` | `test_only_valid_chars` em T16 |
| G8 | Fase 5 (GraphWriter) é chamada de forma sequencial | Sem `await writer.write_*` no coordinator |

---

## Comando para verificar guardrails

```bash
# G1: parsing não importa de extraction/graph/mcp
python -c "
import ast, sys
from pathlib import Path
for f in Path('src/design_graph/parsing').glob('*.py'):
    tree = ast.parse(f.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            name = getattr(node, 'module', '') or ''
            if any(x in name for x in ['extraction', 'graph', 'mcp']):
                print(f'VIOLATION: {f}:{node.lineno}: {name}')
                sys.exit(1)
print('G1 OK')
"

# G3: reader sem writes
grep -n "CREATE\|DELETE\|MERGE" src/design_graph/graph/reader.py && echo "VIOLATION" || echo "G3 OK"
```

Estes checks podem ser integrados ao CI como step de lint.
