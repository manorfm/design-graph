# T40 — Normalização de rótulo de token malformado

**Arquivos:** `src/design_graph/parsing/token_extractor.py`
**Depende de:** —
**Status:** `[x] done`

## Responsabilidade

Impedir que um valor de token que não sobrevive à normalização como
numérico limpo (ex. `"8,"` em vez de `"8"`) seja publicado com um rótulo
corrompido (`radius_8,`) em vez de ser descartado. Auditar as funções de
rótulo irmãs (spacing, font-size, font-weight, shadow) pelo mesmo padrão
de fallback antes de assumir que o bug é exclusivo de radius.

## Critério de aceite

- `_normalise_radius` (ou o portão de normalização equivalente) descarta —
  antes de entrar no `Counter` de ocorrências — qualquer valor que não seja
  um numérico limpo com sufixo opcional `px`/`%`. Valor com vírgula,
  espaço interno ou qualquer caractere fora desse formato não vira token.
- `_radius_label` deixa de ter um caminho que devolve `v[:12]` cru como
  rótulo — se o valor chegou até essa função, já é garantidamente
  numérico limpo (contrato reforçado pelo portão acima, não checado de
  novo ali).
- Auditoria registrada no próprio task (ou em teste) confirmando se
  `_extract_spacing`, `_extract_font_size`/`_extract_font_weight` e
  `_extract_shadow` têm o mesmo formato de fallback sujo; cada uma que
  tiver recebe a mesma correção, cada uma que não tiver ganha um teste de
  regressão registrando que já está correta.
- `get_tokens(category=radius)` (e as categorias irmãs auditadas) nunca
  mais devolve um rótulo com pontuação sobrando.
- Suíte completa (`pytest tests/unit/ -q`) sem regressão; rebuild real
  contra `iPede Manager v15.1.html` sem nenhum token `radius_\d+,` (ou
  equivalente nas categorias irmãs) na saída de `get_tokens`.

## Nota de auditoria (categorias irmãs)

Confirmado em código: **radius era a única categoria com o fallback
perigoso** (`_radius_label`'s `f"radius_{v[:12]}"`). Spacing e font-size já
descartavam valor não-numérico silenciosamente (`try/except ValueError:
pass`, sem fallback de rótulo). Font-weight é limpo por construção — o
próprio `RE_FONT_WEIGHT` só casa `\d{3,4}|bold|semibold`, sem cauda
permissiva capaz de vazar vírgula ou referência de token. Shadow não deriva
rótulo do valor (usa `shadow_{rank}`), então não tem essa classe de bug.
Cada uma virou teste de regressão (`test_garbage_after_weight_keyword_never_reaches_a_label`
para font-weight), não uma correção.

## Fora de escopo

- Introduzir um value object `RadiusValue`/`SpacingValue` novo — o fix é
  fechar o portão de normalização já existente, não modelar um tipo
  paralelo (ver `spec.md` → Entidades ricas, YAGNI explícito).
- Mudar os limiares de classificação por t-shirt size (`xs/sm/md/lg/xl`)
  — nenhum gap relatado ali, só no fallback de valor malformado.
