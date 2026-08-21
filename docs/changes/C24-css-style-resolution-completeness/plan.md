# Plan C24 — Completude da resolução de estilo (CSS embutido + spread)

## Objetivo

Fechar P1–P3 de `spec.md` sem regredir C09–C23, mantendo as guardrails de
arquitetura (G1–G11).

## Critério de aceite

```bash
pytest tests/unit/ -q
pytest tests/test_architecture_guardrails.py -q
design-graph "iPede Manager v15.1.html" --force --db /tmp/c24-rebuild.db
design-graph validate --db /tmp/c24-rebuild.db
```

Rebuild real sempre contra `/tmp` — nunca a DB de produção do repositório.

## Ordem de implementação recomendada

```
T44  parsing/source_loader.py              (P1) — independente
T45  parsing/css_class_resolver.py +       (P2) — depende de T44:
     extraction/component_extractor.py            sem CSS chegando a
                                                    sources.css, T45 não
                                                    tem nenhum insumo real
                                                    para resolver contra
T46  extraction/component_extractor.py      (P3) — independente, pode
                                                    rodar em paralelo a
                                                    T44/T45
```

## Sequência por task

### T44 — CSS de `<style>` estático em `inner_html` (P1)

**RED:** `test_style_tag_inside_inner_html_is_captured_for_bundled_react`
— carregar `iPede Manager v15.1.html` de verdade (fixture já usada por
`tests/integration/`) via `source_loader.load()`; hoje `sources.css ==
""` mesmo com um `<style>` real presente em `sources.inner_html`
(confirmado por execução direta nesta investigação). O teste afirma que
uma classe conhecida do arquivo (`.pulse-dot` ou equivalente) aparece em
`sources.css` depois do fix.

**GREEN:** `_extract_bundled_react` (`source_loader.py`), depois de
resolver `inner_html` (incluindo o fallback `str(soup)`), passa por
`BeautifulSoup(inner_html, "html.parser").find_all("style")` e soma o
texto de cada tag encontrada a `css_parts` antes do `"\n".join`. Mesma
técnica que `_extract_plain` já usa para seu próprio HTML — nenhuma
lógica de parsing nova.

**Regressão:** um bundle com entrada CSS separada (mime contendo `"css"`)
continua contribuindo normalmente — a nova fonte só soma, nunca substitui
`css_parts` já preenchido pelo scan de entradas do bundle.

### T45 — Seletor de tag + pseudo-classe (P2)

*Depende de T44.*

**RED:** `test_tag_selector_list_resolves_to_focus_interaction_on_matching_component`
— CSS real (`input:focus, select:focus, textarea:focus { outline: none;
border-color: #FFB81C; }`, o texto verificado em `iPede Manager
v15.1.html`) + um componente sintético cujo JSX renderiza `<input
type="number" />` — depois do fix, o componente tem uma `InteractionEntry`
(ou `StyleEntry` em estado `focus`) com `borderColor: #FFB81C`.
`test_non_matching_tag_is_not_affected` — o mesmo CSS não afeta um
componente que só renderiza `<div>`.

**GREEN:** nova função em `css_class_resolver.py` (nome próprio, não uma
extensão de `resolve_classes`) que parseia listas de seletor
`tag:pseudo, tag:pseudo, ... { corpo }` em `dict[tag, dict[pseudo,
list[CssRule]]]`. `component_extractor.py` consulta esse mapa pelo nome
de tag HTML que o próprio componente renderiza (mesma detecção de tag já
usada — ou uma extensão mínima dela — para identificar elementos nativos)
e grava as propriedades resolvidas como `StyleEntry`/`InteractionEntry`
no estado `hover`/`focus` correspondente.

### T46 — Resolução de spread em `style={{...}}` (P3)

**RED:** `test_style_spread_reference_is_resolved` — `const inputStyle =
{ height: 34, padding: '0 12px' }` + `style={{...inputStyle, width:
34}}` no mesmo componente — spec do componente inclui `height`, `padding`
e `width`. `test_local_property_overrides_spread_property` — mesma
propriedade definida em `inputStyle` e localmente no bloco: valor local
vence. `test_unresolvable_spread_does_not_break_extraction` — spread sem
`const` correspondente no arquivo: comportamento de hoje preservado
(token ignorado, resto do bloco extraído normalmente).

**GREEN:** no laço de extração de estilo inline de
`component_extractor.py`, detectar um token `...identificador` dentro do
bloco capturado por `RE_INLINE_STYLE`; se encontrado, buscar `const
identificador = {` no `js` completo (não só no `window` do componente —
objetos de estilo compartilhados costumam ser módulo-level) e usar
`find_matching_delimiter` para isolar o corpo do objeto; aplicar a mesma
extração de propriedades a esse corpo, mesclando com as propriedades já
capturadas localmente (`seen_props` decide precedência — local já
processado primeiro vence, mesmo comportamento de dedup já usado hoje
para o bloco principal).

## Validação end-to-end

Rebuild real contra `iPede Manager v15.1.html` (DB descartável em `/tmp`),
comparado ao estado pós-C23 (mesmo arquivo, sem as mudanças deste change):

```
Métrica                  | pós-C23 (baseline) | pós-T44+T45 | pós-T46 (final)
---------------------------|---------------------|--------------|----------------
sources.css (bytes)        | 0                   | 2954         | 2954
CSS class rules resolvidas | 0                   | 10           | 10
Tag pseudo-class rules     | 0                   | 3            | 3
Styles (total no grafo)    | 3832                | 3948 (+116)  | 4013 (+65)
Screens/Components/CONTAINS| 17 / 172 / 343      | inalterado   | inalterado
```

`design-graph validate --db <pós-C24>`: `status=ok errors=0 warnings=0`.

Leitura: T44 é o que destrava tudo (CSS deixa de ser 0 bytes); T45 soma
+116 estilos de foco/hover resolvidos por tag nativa; T46 soma mais +65
resolvendo spreads de objeto de estilo — os três efeitos são aditivos e
mensuráveis no mesmo protótipo de referência, não só nos testes
sintéticos.
