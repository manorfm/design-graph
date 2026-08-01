# Spec C19 — Desambiguação de variantes de JSX concatenadas

## Problema

Quando o mesmo nome de componente é declarado mais de uma vez no
código-fonte (comum em prototypes grandes montados a partir de múltiplos
arquivos/telas concatenados sem escopo de módulo), `ExtractedComponent.consolidate()`
junta o JSX de todas as variantes com um separador genérico
(`{/* Source variant */}`), sem nenhuma indicação de qual implementação é
a que de fato roda no navegador.

Confirmado contra o código-fonte real do `iPede Manager v15.1.html`:
`Btn` e `Modal` têm cada um **duas declarações top-level** (`function Btn(...)`),
sem nenhum wrapper de escopo (IIFE, módulo) entre elas — texto puro
concatenado, ambas em profundidade de indentação zero. Isso é
redeclaração padrão de função no JS: `function Nome(...)` é hoisted
inteiro, e uma declaração posterior no mesmo escopo **substitui
completamente** a anterior — só a última jamais executa. A primeira é
código morto inalcançável.

O relatório anterior (C18) já tinha identificado isso como gap real, mas
adiado a pedido do usuário por exigir mais decisão de design.

## Restrição encontrada durante a implementação

Existe um teste já estabelecido
(`test_duplicate_definitions_are_consolidated_without_losing_variants`)
que exige explicitamente que **nenhuma variante seja descartada** — a
filosofia de design deliberada deste projeto é "não perder informação".
Isso descarta a solução óbvia de "manter só a última variante" (que seria
tecnicamente mais correta em relação à semântica do JS, mas contradiz uma
decisão de design já testada e não solicitada para mudança).

## Solução

`_label_jsx_variants()` (novo, `core/models.py`) — mantém **todas** as
variantes (nenhuma perda de informação, teste antigo continua passando
sem alteração), mas rotula cada uma com sua posição declarativa e se é a
que executa:

```
{/* Variant 1/2 — shadowed by a later declaration, never executes */}
<button>...</button>

{/* Variant 2/2 — live (last declaration wins in JS) */}
<button>...</button>
```

`variants` chega em `consolidate()` já em ordem de posição no código-fonte
(`extract_all_components` preserva a ordem de `boundaries`, que
`find_all_boundaries` já garante ordenada por posição) — a última
variante da lista é, por definição, a última declaração no arquivo, e
portanto a que vence a redeclaração do JS.

Com exatamente 1 variante (caso comum, sem duplicação), nenhum rótulo é
adicionado — comportamento idêntico ao anterior, sem ruído.

## Invariantes

- Nenhuma variante é descartada — mesmo teste de "sem perder variantes"
  continua passando sem modificação.
- Com 1 variante, `jsx_snippet` é devolvido sem qualquer rótulo.
- A última variante (ordem de código-fonte) é sempre rotulada "live"; toda
  variante anterior é rotulada "shadowed".
- Nenhuma mudança em `styles`/`interactions`/`texts`/`props`/`child_refs`
  — a fusão desses campos continua união de todas as variantes (fora de
  escopo desta change; só o campo `jsx_snippet` mudou).

## Fora de escopo

- Detectar declarações condicionalmente aninhadas (`function` dentro de um
  `if`) onde a semântica "última declaração vence" não se aplica da mesma
  forma — o parser é baseado em regex, sem AST, não distingue esse caso do
  caso comum (declaração top-level incondicional). Não observado no
  prototype de referência (ambas declarações de `Btn`/`Modal` estão em
  indentação zero, incondicionais).

## Arquivos afetados

| Arquivo | Mudança |
|---|---|
| `src/design_graph/core/models.py` | `_label_jsx_variants()`; `ExtractedComponent.consolidate()` usa o helper em vez de `"\n\n{/* Source variant */}\n\n".join(...)` |
| `tests/unit/core/test_models.py` | `TestExtractedComponentConsolidateSingleVariant` |
| `tests/unit/extraction/test_component_extractor.py` | `test_duplicate_definitions_label_which_variant_actually_executes` |
