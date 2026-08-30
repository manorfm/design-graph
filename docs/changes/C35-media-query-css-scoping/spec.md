# Spec C35 — Parsing: `@media` corrompe a resolução de classe CSS

## Contexto

Investigação disparada por um relato de outro agente (sessão externa, projeto
consumidor): "design-graph não expõe media queries, decodifiquei o bundle
comprimido do protótipo real (v2.2) na mão pra achar as media queries de
verdade". A alegação foi verificada contra este repositório usando
`toToggle v2.2.html` (protótipo real, presente na raiz do projeto, formato
`bundled_react` com bundler `__bundler/*` — nunca usado como fixture de
nenhum change anterior).

Duas partes da alegação, verificadas separadamente:

1. **"Design-graph não expõe media queries"** — confirmado. `C10` (linha 36),
   `C11` (linha 105) e `C29` (linhas 47–50, "Fora de escopo") documentam,
   três vezes, a decisão deliberada de não modelar `@media`/breakpoint no
   schema. `StyleState` (`core/models.py:102`) só tem `DEFAULT`/`HOVER`/`FOCUS`.
2. **"Precisei decodificar o bundle na mão"** — **falso, e é a parte
   acionável deste spec**. `source_loader.py` já decodifica
   `toToggle v2.2.html` corretamente sem nenhuma mudança: `format=bundled_react`,
   via o branch de "short JSON string containing inner HTML"
   (`source_loader.py:106-114`), e o `RawSources.css` resultante **já contém
   os 7 blocos `@media` do protótipo, verbatim**:

   ```
   @media (min-width:1600px){ ... }
   @media (min-width:1180px) and (max-width:1599px){ ... }
   @media (max-width:1180px){ ... }
   @media (max-width:1024px){ ... }
   @media (hover:none){ ... }
   @media (max-width:600px){ ... }
   @media (max-height:480px) and (orientation:landscape){ ... }
   ```

   Ou seja: a decompressão do bundle não é o problema. O texto certo já
   chega até `css_class_resolver.py`. O problema é o que esse módulo faz com
   ele.

## Problema

### P1 — `extract_css_rules`/`extract_tag_pseudo_rules` não respeitam fronteira de `@media` — corrompem o valor default (crítico)

`css_class_resolver.py` documenta a intenção de **ignorar** `@media`
(spec C10, linha 36: "Ignores pseudo-classes, @media, :hover, etc."). Na
prática, ele não ignora — ele **absorve** como se fosse regra incondicional:

- `_RE_SIMPLE_CLASS_BLOCK` (linha 35) e `_RE_SELECTOR_BLOCK` (linha 49) são
  `finditer`/`findall` sobre o texto CSS **inteiro**, sem noção de
  aninhamento. Um bloco `.foo { ... }` dentro de `@media (...) { .foo {
  ... } }` casa exatamente igual a um `.foo { ... }` de top-level.
- `extract_css_rules` (linha 393) faz `result[cls_name] = rules` —
  **sobrescreve**, não acumula. Quando a mesma classe aparece mais de uma
  vez no CSS (default + variante(s) responsiva(s)), só a **última ocorrência
  na ordem textual do arquivo** sobrevive — que pode ser a versão dentro de
  um `@media`, dependendo de onde o autor do protótipo colocou o bloco.
- `extract_tag_pseudo_rules` (linha 434, `result.setdefault(tag,
  {})[pseudo_class] = rules`) tem a mesma falha para seletores `tag:pseudo`.
- Nada entre `source_loader.load()` (`pipeline/coordinator.py:269-270`) e
  essas duas funções remove ou isola o conteúdo de `@media` antes do parse.

**Evidência real, `toToggle v2.2.html`** — classe `.page-title`, duas
declarações no CSS extraído (`RawSources.css`):

| Offset | Contexto | Declaração |
|---|---|---|
| 17492 (top-level) | regra real, sempre ativa | `.page-title { font-size: 25px; font-weight: 600; letter-spacing: -0.025em; }` |
| 65680 (dentro de `@media (max-width:600px)`) | só ativa em viewport ≤600px | `.page-title{font-size:21px}` |

`extract_css_rules(rs.css)['page-title']` retorna **apenas**
`[CssRule('.page-title', 'font-size', '21px')]`. Isso significa:

- `font-weight` e `letter-spacing` desaparecem inteiramente — nenhum agente
  consegue perguntar "qual o peso da fonte do título?" e receber resposta
  correta.
- O `font-size` retornado (`21px`) é o valor de **mobile ≤600px**,
  apresentado sem qualquer indicação de condição — um agente que chame
  `get_component_spec`/`resolve_classes` para qualquer componente com
  `className="page-title"` recebe silenciosamente o valor errado para o
  caso comum (desktop), com confiança igual a qualquer outro campo do grafo.
- O resultado é nu-determinístico do ponto de vista do consumidor: depende
  da ordem em que o autor do protótipo escreveu as regras no CSS-fonte, não
  de nenhuma lógica de cascata real (media query real depende de largura de
  viewport, não de posição no arquivo).

Mesmo padrão reproduzido em `.crumbs`, `.page-desc`, `.app` (verificado
nesta investigação) — não é um caso isolado de uma classe; é sistemático
para toda classe que tem qualquer override dentro de `@media`.

### P2 — nenhum dado responsivo é preservado em lugar nenhum (feature, não bug)

Consequência de P1 resolvido corretamente (ignorar de verdade, não
absorver): o conteúdo dos 7 blocos `@media` do protótipo real fica
descartado, não apenas "não modelado". `C29` (linhas 101–105) já registrou
que breakpoint não tem eixo no schema por falta de "evidência de qual
formato seria o certo" — `toToggle v2.2.html` é essa evidência: 7 media
queries reais, formato consistente (`min-width`/`max-width` em px,
combinações com `and`, e o caso não dimensional `hover:none`).

## Solução proposta

| Task | Problema | Camada |
|---|---|---|
| T77 | P1 | `parsing/css_class_resolver.py` |
| T78 | P2 | `parsing/css_class_resolver.py`, `core/models.py`, `mcp/tools.py` |

**T77** — nova função `_strip_media_blocks(css_text: str) -> tuple[str,
list[tuple[str, str]]]` em `css_class_resolver.py`: varre `css_text`
procurando `@media`, localiza o corpo por contagem de profundidade de
`{`/`}` (mesma disciplina de colapso balanceado já usada em C21 para JSX;
aqui aplicada a CSS), e retorna `(css_sem_media, [(condicao, corpo), ...])`.
`extract_css_rules` e `extract_tag_pseudo_rules` passam a rodar só sobre
`css_sem_media` — elimina P1 sem exigir nenhuma mudança de schema. A lista
de `(condicao, corpo)` fica disponível para T78; se T78 não for feito nesta
rodada, ela é apenas descartada e o comportamento passa a ser "ignora de
verdade", que é exatamente o que a docstring de `extract_css_rules` já
promete hoje.

Guardrail: `_strip_media_blocks` não interpreta a condição da media query
(não normaliza `min-width`/`max-width` em breakpoint nomeado) — guarda a
string crua entre `@media` e `{`, mesma disciplina de "não inventar
categoria sem padrão confirmado" já aplicada em C24 a `styled-components`.

**T78** (proposto; pode ser adiado para change separado se T77 sozinho já
for aceito como suficiente para esta rodada) — `CssRule` ganha campo
opcional `media: str | None = None`; `extract_css_rules` roda uma segunda
vez sobre cada `(condicao, corpo)` de T77, atribuindo `media=condicao` às
regras resultantes, guardadas num `dict[str, list[CssRule]]` separado
(`responsive_rule_map`) — nunca misturado ao `rule_map` default, para não
reabrir P1 por outra via. `StyleEntry.from_css_class` ganha parâmetro
`media: str | None = None`; quando presente, o `id` inclui a condição no
seed (mesmo padrão de `state` em C29) para não colidir com a entrada
default da mesma classe/propriedade. Exposição: `get_component_spec`
(`mcp/tools.py:1090`) ganha uma seção "Estilos responsivos" opcional,
listada só quando o componente resolve alguma classe com entrada em
`responsive_rule_map` — nenhuma tool nova, reaproveita a tool existente
mais consultada para estilo de componente.

## Cobertura de testes exigida

- **T77**: `TestStripMediaBlocks` — bloco `@media` simples; bloco com `and`
  composto (`@media (min-width:1180px) and (max-width:1599px)`); `@media`
  aninhado com chaves desbalanceadas dentro de um valor de propriedade
  (`content: "}"` — caso adversarial); CSS sem nenhum `@media` (no-op,
  saída idêntica à entrada). `TestExtractCssRulesIgnoresMedia` — classe com
  declaração default E dentro de `@media`: `extract_css_rules` deve
  retornar **só** a declaração default, com todas as propriedades
  (regressão direta do caso `.page-title` documentado acima, usando um
  fixture minimizado, não o arquivo de 1.5MB inteiro).
  `TestExtractTagPseudoRulesIgnoresMedia` — mesmo caso para seletor
  `tag:pseudo` dentro de `@media`.
- **T78** (se implementado): `TestResponsiveRuleMapSeparateFromDefault` —
  classe com regra default e regra responsiva não colidem em `rule_map`;
  `test_from_css_class_media_seed_differs_from_default` (mesmo padrão de
  `test_from_css_class_hover_state_seed_includes_state_name` de C29).

Suíte completa (`pytest tests/unit/ -q`, `pytest tests/integration/ -q`) sem
regressão e guardrails (`pytest tests/test_architecture_guardrails.py -q`)
intactas; rebuild real contra `iPede Manager v21.2.html` **e**
`toToggle v2.2.html` (DBs descartáveis em `/tmp`) reportado no `plan.md` —
o segundo arquivo agora fica registrado como fixture de referência para
`@media`, do mesmo jeito que o primeiro já é para o resto do pipeline.

## Segurança

Nenhuma nova fronteira de I/O — `_strip_media_blocks` opera só sobre texto
CSS já carregado do arquivo local do protótipo, mesma superfície de
`extract_css_rules` hoje. Contagem de profundidade de chaves é limitada ao
tamanho do CSS de entrada (mesma ordem de grandeza já processada sem
timeout por `_RE_SIMPLE_CLASS_BLOCK`); nenhum laço `while True` sem
condição de parada baseada em progresso do cursor.

## Fora de escopo

- Normalizar condições de `@media` em breakpoints nomeados (`sm`/`md`/`lg`)
  — nenhuma evidência de que `toToggle v2.2.html` ou `iPede Manager
  v21.2.html` usem um sistema de breakpoint compartilhado; guardar a
  condição crua (T78) é suficiente e evita inventar taxonomia sem padrão
  confirmado em dois protótipos reais.
- Cascata real de media queries (resolver qual regra vence quando várias
  condições se sobrepõem em runtime, ex. `min-width` e `max-width`
  simultâneos) — fora do que um agente de UI normalmente precisa (ele quer
  saber "que estilos existem e sob que condição", não simular um browser).
- `dark:`/tema — mesmo motivo já registrado em C29, inalterado por este
  spec.
- Extrair `@media` de dentro de `js` (CSS-in-JS via `styled-components` ou
  similar) — este spec cobre só `RawSources.css`; nenhuma evidência de
  `@media` em `RawSources.js` nos dois protótipos de referência (confirmado
  nesta investigação: 0 ocorrências em `rs.js` para `toToggle v2.2.html`).
