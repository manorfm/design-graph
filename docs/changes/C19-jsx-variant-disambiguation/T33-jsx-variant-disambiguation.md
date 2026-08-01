# T33 — Desambiguação de variantes de JSX

**Arquivo:** `src/design_graph/core/models.py`
**Depende de:** T27 (`ExtractedComponent.consolidate`, DDD refactor)
**Status:** ✅ done

## Responsabilidade

Rotular, sem descartar, qual variante de um componente com múltiplas
declarações de mesmo nome é a que realmente executa no navegador (última
declaração vence, por redeclaração padrão do JS).

## Critério de aceite

- `_label_jsx_variants()` — com 1 variante, retorna o JSX sem nenhum
  rótulo (comportamento idêntico ao anterior). Com 2+ variantes, rotula
  cada uma com posição (`Variant N/total`) e status (`live`/`shadowed`).
- A última variante da lista (ordem de código-fonte, garantida por
  `find_all_boundaries`) é sempre a rotulada "live".
- Nenhuma variante é descartada — teste pré-existente
  `test_duplicate_definitions_are_consolidated_without_losing_variants`
  continua passando sem modificação.
- `styles`/`interactions`/`texts`/`props`/`child_refs` continuam sendo
  união de todas as variantes — só `jsx_snippet` muda.
- Testes novos: `TestExtractedComponentConsolidateSingleVariant`
  (models), `test_duplicate_definitions_label_which_variant_actually_executes`
  (extraction, ponta a ponta).
- Suíte completa (`pytest -q`) sem regressão — 1564 testes.
- Validado contra o prototype real: `Btn`/`Modal` (2 declarações
  `function` top-level cada, confirmadas sem wrapper de escopo) mostram os
  rótulos corretos via `design-query inspect`.
