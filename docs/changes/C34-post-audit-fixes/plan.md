# Plan C34 — Correções pós-auditoria

## Objetivo

Fechar P1–P5 de `spec.md` sem regredir C01–C33, mantendo as guardrails de
arquitetura.

## Critério de aceite

```bash
pytest tests/unit/ -q
pytest tests/integration/ -q
pytest tests/test_architecture_guardrails.py -q
design-graph "iPede Manager v21.2.html" --force --db /tmp/c34-rebuild.db
design-graph validate --db /tmp/c34-rebuild.db
```

Rebuild real sempre contra `/tmp` — nunca a DB de produção do repositório.

## Ordem de implementação

```
T72  extraction/alias_extractor.py                                  — independente
T73  graph/writer.py                                                 — independente
T74  mcp/tools.py                                                     — independente
T75  extraction/screen_extractor.py + extraction/section_extractor.py — independente
T76  extraction/component_extractor.py                                — independente
```

Todos independentes entre si — nenhuma dependência, todos tocam arquivos
diferentes.

## Validação end-to-end

Rebuild real contra `iPede Manager v21.2.html` (DB descartável em `/tmp`),
comparado ao estado pós-C33 (mesmo arquivo, sem as mudanças deste change):

```
Métrica                     | pós-C33 (baseline) | pós-C34 (final)
-------------------------------|---------------------|------------------
screens / tokens                | 14 / 86             | 14 / 86 (inalterado)
sections                        | 64                  | 64 (inalterado)
components                      | 192                 | 182 (-10)
unresolved_components           | 16                  | 6 (-10)
contains_rels                   | 429                 | 419 (-10)
interactions                    | 30                  | 26 (-4)
write_errors                    | 0                   | 0
```

Leitura:
- **-10 components/unresolved/contains**: exatamente os 10 nomes de Screen
  (`CategoriesPage`, `ClientItemDetail`, `DashboardPage`,
  `IngredientsPage`, `InventoryPage`, `ItemEditorV6`, `PlaceholderPage`,
  `PromotionsPage`, `RestaurantDetail`, `RestaurantsPage`) que P2/T73
  parou de materializar como shell fantasma — confirmado nome a nome
  comparando a lista de `occurrence=0` antes/depois.
- **-4 interactions**: P5/T76 eliminando entradas duplicadas onde a mesma
  propriedade era mutada duas vezes no mesmo handler — menos entradas,
  mais corretas (cada propriedade agora aparece uma vez, com o valor
  realmente efetivo em runtime).
- **Ordem de `CONTAINS` confirmada não-alfabética após P1/T72**: `BasicTab`
  (mesmo componente citado no plan.md do C30) agora sai como `Card,
  SectionTitle, Field, TextInput, Sel, TextArea, IconBtn, Btn, NumInput,
  SwitchRow, Segmented, Chip, Pill` — não mais uma sequência que parece
  alfabética. Confirma que a observação registrada em C30 era este bug,
  não uma característica do bundle original.
- Os 6 `occurrence=0` restantes (`KField`, `KSel`, `KTextInput`,
  `MenuItem`, `PromoIcon`, `TemplatesPageV6`) foram inspecionados
  individualmente — nenhum é nome de Screen declarada; `TemplatesPageV6`
  parece nome de tela mas não está em `_declared_screen_names` neste
  protótipo por razão própria (não extraída como Screen), não uma falha
  do fix de P2.

`design-graph validate --db /tmp/c34-rebuild.db`: `status=ok errors=0
warnings=0` (14 screens, 182 components, 64 sections, 86 tokens, 419
CONTAINS).

Suíte: `pytest tests/unit/ -q` → 1756 passed (13 novos testes, 2 asserções
de teste existente corrigidas). `pytest tests/integration/ -q` → 155
passed. `pytest tests/test_architecture_guardrails.py -q` → 22 passed.
