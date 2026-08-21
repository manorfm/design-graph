# Spec C24 — Completude da resolução de estilo (CSS embutido + spread)

## Contexto

Continuação do C23. Um log real de chamadas MCP contra o servidor
(prototype `ipede_manager_v21.1`, componente `NumInput` — um `<input
type="number">` com stepper nativo do navegador) trouxe 4 suspeitas de
gap. Duas foram confirmadas e viraram este change; duas ficaram fora por
falta de evidência (ver Fora de escopo). O prototype `ipede_manager_v21.1`
em si não está neste repositório — toda causa raiz abaixo foi verificada
contra `iPede Manager v15.1.html`/`v21.html` (já versionados aqui) e
contra o código-fonte real do `design-graph`, nunca contra o log em si.

## Problemas identificados

### P1 — CSS de `<style>` estático no HTML nunca chega a `sources.css` (bundled_react)

Execução real de `source_loader.load()` contra `iPede Manager v15.1.html`
confirma: `sources.css` tem **0 bytes**; `sources.inner_html` (4692 bytes)
contém um `<style>...</style>` literal com regras reais — incluindo
`input:focus, select:focus, textarea:focus { outline: none;
border-color: #FFB81C !important; box-shadow: 0 0 0 3px
rgba(255,184,28,0.12); }` e classes como `.pulse-dot`, `.icon-btn`.

`_extract_bundled_react` (`parsing/source_loader.py`) só coleta CSS de
entradas do bundle JSON cujo `mime` contém `"css"` — nunca examina o
`<style>` que já está dentro do `inner_html` resolvido (o HTML estático
que a página carrega antes do React hidratar). Log do build real confirma
o efeito: `"pipeline: resolved 0 CSS class rules from stylesheet"` — **zero
regras CSS de qualquer tipo** são resolvidas para esse prototype inteiro,
não só a regra de foco relatada. É a causa raiz mais alta do lote: sem
ela, nada do resto deste change (P2) tem efeito observável em prototypes
`bundled_react` — o formato usado pelo próprio iPede Manager.

### P2 — `css_class_resolver` não resolve seletor de tag + pseudo-classe

`extract_css_rules` (`parsing/css_class_resolver.py`) só casa `.classe {
... }` — a própria docstring documenta a exclusão: "Pseudo-classes
(:hover, :focus), element selectors (div), and ID selectors (#id) are
deliberately ignored — they cannot be resolved from className strings."
Verdade para seletores de classe (não há como saber se um dado elemento
tem uma classe sem examinar o próprio JSX), mas **falsa para seletor de
tag pura** (`input:focus`) — o próprio nome da tag renderizada já é
suficiente para saber se a regra se aplica, sem precisar de nenhuma
`className`. `resolve_classes` é indexado só por nome de classe; não há
nenhum caminho de resolução por nome de tag.

Consequência combinada com P1: mesmo depois de corrigir P1, `NumInput`
(que renderiza `<input type="number">`) continua sem nenhuma interação de
foco no grafo — a regra chega a `sources.css`, mas ninguém a associa ao
componente.

### P3 — Spread num objeto de `style={{...}}` é descartado sem resolução

`RE_STYLE_PROP` (`core/patterns.py`) exige forma `chave: valor` —
confirmado por teste direto: `...inputStyle, textAlign: 'center', width:
34` produz só `[('textAlign','center'),('width','34')]`; o token
`...inputStyle` não corrompe as propriedades vizinhas, mas some sem
deixar rastro. Busca por "spread" em `extraction/`, `parsing/` e
`core/patterns.py`: nenhum resultado — não existe, em lugar nenhum do
pipeline, um mecanismo que resolva `...identificador` de volta ao objeto
`const identificador = { ... }` que ele referencia. A spec de `NumInput`
mostra `type="number"` mas nunca os valores reais de altura/padding/raio
que `inputStyle` carrega.

## Solução proposta

| Task | Problema | Camada | Depende de |
|---|---|---|---|
| T44 | P1 | `parsing/` (`source_loader.py`) | — |
| T45 | P2 | `parsing/` (`css_class_resolver.py`) + `extraction/` (`component_extractor.py`) | T44 (sem CSS chegando ao resolver, nada aqui tem efeito observável) |
| T46 | P3 | `extraction/` (`component_extractor.py`) | — |

**T44** — `_extract_bundled_react` passa a também extrair `<style>` do
`inner_html` já resolvido (mesma técnica que `_extract_plain` já usa:
`BeautifulSoup(...).find_all("style")`), somando ao CSS já coletado de
entradas do bundle — aditivo, nunca substitui uma fonte por outra.

**T45** — novo caminho de resolução, paralelo a `resolve_classes`
(não uma extensão dele — `resolve_classes` documenta seu contrato como
"indexado por className", misturar tag-selector ali quebraria essa
promessa): parseia listas de seletor `tag:pseudo, tag:pseudo, ... { ... }`
em um mapa `tag → pseudo-classe → propriedades`. `component_extractor.py`
consulta esse mapa pelo próprio nome de tag renderizado pelo componente
(`<input`, `<select`, `<textarea`, ...) e grava as propriedades como
`InteractionEntry`/`StyleEntry` no estado (`hover`/`focus`) correto — mesmo
vocabulário de estado já usado pelas interações vindas de handler JS
(C12/C13), não um estado novo.

**T46** — quando o bloco de `style={{...}}` de um componente contém um
token de spread (`...identificador`), busca no mesmo arquivo por `const
identificador = { ... }` (scan balanceado, mesma técnica de
`parsing.js_parser.find_matching_delimiter` já usada em C13/C21/C23) e
resolve as propriedades literais desse objeto como parte do estilo do
componente. Simplificação documentada: propriedade que já existe
localmente no bloco vence a mesma propriedade vinda do spread — não é a
ordem exata de merge do JS (que depende da posição textual do `...spread`
relativa a cada chave), mas cobre o padrão real observado (`{...base,
overrides}`) sem exigir rastreamento posicional.

## Entidades ricas e value objects

- **`CssRule`** (já existe, `css_class_resolver.py`) — reusado tal como
  está para T44 (nenhuma mudança de forma; só mais texto chega até ele) e
  para os corpos de regra de T45. Nenhum campo novo.
- **T45 não introduz um "TagRule" paralelo a `CssRule`** — mesmo tipo
  `CssRule` (`selector`, `property`, `value`), só que agora `selector`
  também pode conter algo como `"input:focus"` em vez de `".classe"` — o
  tipo já é genérico o suficiente; um tipo novo só para diferenciar a
  origem seria distinção sem uso real (nada consome `CssRule.selector`
  para decidir comportamento hoje).
- **T46 não introduz um "SpreadRef" value object** — resolve inline,
  reusando `StyleEntry.create()` (C14) para cada propriedade encontrada,
  igual a qualquer outra propriedade de estilo já extraída.

## Cobertura de testes exigida

- **P1/T44**: `iPede Manager v15.1.html` real (fixture já usada por
  outros testes de integração) com `<style>` no `inner_html` → CSS
  extraído não fica vazio; classes conhecidas do arquivo (`.pulse-dot`)
  aparecem no `rule_map`. Regressão: um bundle que já tinha entrada CSS
  separada (mime `text/css`) continua funcionando — a nova fonte é
  aditiva, não substitui.
- **P2/T45**: seletor único (`input:focus { ... }`); lista de 3 seletores
  compartilhando um corpo (`input:focus, select:focus, textarea:focus`);
  componente que renderiza `<input>` recebe a interação de foco;
  componente que renderiza `<div>` não recebe (tag não bate).
- **P3/T46**: `style={{...inputStyle, width: 34}}` com `const inputStyle
  = {...}` definido no mesmo arquivo — propriedades de `inputStyle`
  aparecem na spec; propriedade repetida localmente (`width` definido nos
  dois lugares) mantém o valor local. Regressão: spread sem `const`
  correspondente encontrável não quebra a extração (comportamento de hoje
  — token ignorado — preservado como fallback).

Suíte completa (`pytest tests/unit/ -q`) sem regressão e guardrails
(`pytest tests/test_architecture_guardrails.py -q`) intactas ao final de
cada task; rebuild real contra `iPede Manager v15.1.html` reportado no
`plan.md`.

## Segurança

- Nenhuma nova fronteira de I/O — as três tasks continuam operando só
  sobre HTML/JS já carregado do arquivo local do prototype.
- T44 reusa `BeautifulSoup(...).find_all("style")`, já em uso por
  `_extract_plain` no mesmo arquivo — nenhum parser novo introduzido.
- T45/T46: qualquer regex nova para seletor de lista (`tag:pseudo, ...`)
  ou para localizar `const identificador = {`, segue balanced-scan via
  `find_matching_delimiter` para o corpo — não regex gananciosa aninhada
  — mesma mitigação de custo já documentada em C13/C23.

## Performance / consumo de tokens

- T44 só roda `find_all("style")` uma vez por build sobre um HTML já em
  memória — custo desprezível frente ao tempo de build já medido (~100s
  no rebuild de referência).
- T45/T46 aumentam a spec de um componente só quando ele de fato usa o
  padrão (tag reconhecida / spread presente) — não infla a resposta de
  componentes não afetados.

## Arquitetura e boas práticas Python

- Guardrails G1/G2 preservados: `source_loader.py`/`css_class_resolver.py`
  continuam em `parsing/`, sem import de `extraction/`/`graph/`/`mcp/`;
  `component_extractor.py` (T45/T46) continua só descendo a cadeia de
  dependência já estabelecida.
- T45 não estende `resolve_classes` — cria um caminho paralelo com nome
  próprio, preservando a responsabilidade única já documentada no
  módulo (resolução por className).
- Nenhuma dependência nova — `BeautifulSoup` (T44) e
  `find_matching_delimiter` (T46) já são dependências existentes do
  projeto.

## Invariantes

- Nenhuma mudança nesta spec altera o formato de saída dos tools MCP para
  componentes já corretos hoje — só os casos com gap ganham dado
  adicional.
- IDs determinísticos (`EntityId`) continuam byte-compatíveis — nenhuma
  task muda a seed de um `StyleEntry`/`CssRule` já existente.
- Rebuild do prototype de referência deve manter ou aumentar toda métrica
  de cobertura já relatada em C09–C23 — nenhuma pode regredir.

## Fora de escopo

- **`search("spin")` não encontrar `NumInput`** (achado 1 do log
  original) — investigado: não é bug de tokenização (T37/C23 já resolveu
  isso), é ausência de conteúdo — nada na extração anota que `type="number"`
  implica comportamento nativo de spinner. Resolver isso de verdade exigiria
  codificar conhecimento de domínio sobre atributos HTML nativos em algum
  lugar da extração — mudança de escopo maior que um fix pontual; candidato a
  investigação própria, não incluído aqui sem uma proposta de onde esse
  conhecimento deveria viver.
- **`search("ordem")` não encontrar o `<span>ordem</span>` do `GroupsTab`**
  (achado 2) — não verificável nesta sessão: nem `NumInput` nem `GroupsTab`
  existem nos prototypes versionados neste repo (`iPede Manager
  v15.1.html`/`v21.html`); o prototype real (`ipede_manager_v21.1`) não
  está disponível aqui. Sem o JSX real, qualquer fix seria baseado em
  paráfrase, não em evidência — na linha do que este projeto já rejeitou
  antes (C23 seguiu a mesma disciplina). Retomar quando houver acesso ao
  prototype real ou um HTML atualizado for versionado.
- **Ordem exata de merge de spread do JS** (T46) — resolução é "spread
  primeiro, local sobrescreve", não rastreamento posicional exato: ver
  Solução proposta.
- **CSS-in-JS via `styled-components`/`emotion`** ou qualquer template
  literal de CSS que não esteja dentro de um `<style>` renderizado no HTML
  estático — T44 resolve especificamente o caso confirmado (um `<style>`
  literal dentro do `inner_html`); outros padrões de CSS-in-JS não foram
  encontrados nos prototypes de referência e ficam fora até haver
  evidência real.

## Riscos e mitigação

| Risco | Mitigação |
|---|---|
| T44 capturar `<style>` de um prototype `plain_html`/`tailwind` em duplicidade (já coberto por `_extract_plain`) | T44 só toca `_extract_bundled_react` — o caminho `_extract_plain` (formatos `plain_html`/`tailwind`) já faz isso e não é alterado |
| T45 aplicar uma regra de tag a um componente que renderiza a tag certa mas em um contexto onde o CSS real não bateria (especificidade/cascata que o extrator não modela) | Documentar como limitação conhecida — mesma classe de aproximação que o resto do resolvedor de CSS já aceita (Tailwind fallback, precedência simples) |
| T46 buscar `const identificador` errado por colisão de nome em arquivo grande | Escopo de busca é o arquivo inteiro (já é assim para outras resoluções de módulo, ex. alias), aceito como o mesmo trade-off já existente em `extract_component_aliases` |

## Arquivos afetados

| Arquivo | Tasks |
|---|---|
| `src/design_graph/parsing/source_loader.py` | T44 |
| `src/design_graph/parsing/css_class_resolver.py` | T45 |
| `src/design_graph/extraction/component_extractor.py` | T45, T46 |
