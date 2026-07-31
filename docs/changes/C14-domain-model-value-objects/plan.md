# Plan C14 — Domain model: value objects, enums, entidades ricas

## Objetivo

Eliminar primitive obsession e duplicação real no domínio, sem mudar
comportamento observável — cada incremento validado contra a suíte completa
antes do próximo.

## Critério de aceite

```bash
pytest tests/unit/core/test_models.py -v
pytest tests/unit/ -q   # suíte completa sem regressão, a cada incremento
design-graph "iPede Manager v15.1.html" --force
design-graph validate --db "<db>"
# BuildStats deve bater exatamente com o baseline pré-refactor
```

## Sequência TDD (executada nesta ordem)

1. **`EntityId`** — `.derive`/`.literal`, incluindo teste de
   byte-compatibilidade contra o algoritmo legado.
2. **Enums + factories no domínio** (`core/models.py`): todos os 9 enums,
   `PropDefault`, `.create()`/`.for_section()`/etc. em `StyleEntry`,
   `TextEntry`, `InteractionEntry`, `ComponentProp`, `ExtractedSection`.
   - **Bug achado em GREEN**: `f"{StyleState.HOVER}"` produzia
     `"StyleState.HOVER"`, não `"hover"` — `(str, Enum)` não corrige
     `__str__`. Corrigido com `_StrEnum` base (`__str__` → `self.value`)
     antes de prosseguir; teste de regressão específico adicionado.
3. **Migração dos produtores de ID**, um módulo por vez, suíte completa
   entre grupos: `component_extractor.py` → `section_extractor.py` →
   `token_extractor.py` → `prop_extractor.py` → `css_class_resolver.py` →
   `graph/writer.py` (fecha os 2 bypasses do model layer).
4. **`ComponentType`/`SemanticType`** tipados em
   `_COMPONENT_TYPE_MAP`, `_SEMANTIC_TYPE_TO_COMP_TYPE`,
   `_infer_semantic_type`, `infer_component_type`.
5. **Correção dos 4 pontos de drift** em `mcp/tools.py`/`cli/query.py` —
   listas de valores válidos passam a derivar dos enums em vez de listas
   soltas redigitadas.
6. **Dedup do fingerprint** `graph/diff.py`/`pipeline/state.py`.
7. **Regressão final**: suíte completa (1539 testes) + rebuild real do
   `iPede Manager v15.1.html` — stats idênticos ao baseline
   (components=173, interactions=72, styles=3856, texts=1369, contains=262,
   props=584) — confirma refactor puro. Teste de mutação deliberado
   (reintroduzir o bug antigo de captura de handler) confirmou que a suíte
   pega regressão de verdade, não só executa linha.

## Nota sobre escopo avaliado e descartado

`cli/report.py::TokenTableRow.category`/`ComponentSummary.comp_type` foram
avaliados como próximo candidato e **descartados**: leem de dict cru vindo
de query Cypher (fronteira externa), sob um `try/except` que retorna `[]`
em qualquer falha — forçar o enum ali trocaria "uma categoria malformada
aparece em branco" por "uma categoria malformada apaga a tabela de tokens
inteira do relatório". Deixado como `str` deliberadamente.
