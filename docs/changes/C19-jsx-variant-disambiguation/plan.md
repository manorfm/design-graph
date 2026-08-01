# Plan C19 — Desambiguação de variantes de JSX

## Objetivo

Fechar o gap adiado em C18 (variantes de componente concatenadas sem
indicação de qual executa), sem violar a decisão de design já testada de
"nunca perder uma variante".

## Critério de aceite

```bash
pytest tests/unit/core/test_models.py -k SingleVariant -v
pytest tests/unit/extraction/test_component_extractor.py -k "variant" -v
pytest tests/unit/ -q   # suíte completa sem regressão, inclui o teste
                        # "without_losing_variants" já existente
design-graph "iPede Manager v15.1.html" --force
design-query inspect Btn --db "<db>"   # confirma rótulo real
```

## Sequência TDD

### Fase 0 — investigação (antes de escrever qualquer código)

Confirmado contra o código-fonte real: `Btn`/`Modal` têm 2 declarações
`function` top-level cada, sem wrapper de escopo — redeclaração JS padrão,
só a última executa. Verificado que existe um teste já estabelecido
exigindo preservar ambas as variantes — descartou a solução
"last-wins-descarta-o-resto" antes de implementar.

### Fase 1 — RED

`test_duplicate_definitions_label_which_variant_actually_executes`
(extraction, ponta a ponta via `extract_all_components`) — a primeira
ocorrência de "First action" deve vir depois de um rótulo contendo
"shadowed", a de "Second action" depois de um rótulo contendo "live".
Falha porque nenhum desses textos existe ainda no separador.

`TestExtractedComponentConsolidateSingleVariant` (models, unitário) — com
1 variante só, nenhum rótulo deve aparecer. Já passava antes (join de
lista de 1 elemento não adiciona separador) — mantido como guarda de
regressão.

### Fase 2 — GREEN

`_label_jsx_variants()` substitui a linha única de `.join()` — itera
`jsx_variants` (já em ordem de código-fonte), rotula a última como "live"
e as anteriores como "shadowed".

### Fase 3 — regressão

Suíte completa, incluindo o teste pré-existente
`test_duplicate_definitions_are_consolidated_without_losing_variants` —
passa sem nenhuma alteração no próprio teste, confirmando que a mudança é
aditiva (só rotulagem), não uma remoção de dados.

## Validação end-to-end

Rebuild real do `iPede Manager v15.1.html` (stats idênticos ao baseline —
mudança é só na formatação do campo `jsx_snippet`). `design-query inspect Btn`
confirma as duas variantes reais do prototype corretamente rotuladas:
variante 1 (linha ~40321 do JS decodificado) como "shadowed", variante 2
(linha ~41067) como "live".
