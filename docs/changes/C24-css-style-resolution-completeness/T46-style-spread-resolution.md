# T46 — Resolução de spread em `style={{...}}`

**Arquivos:** `src/design_graph/extraction/component_extractor.py`
**Depende de:** —
**Status:** `[x] done`

## Responsabilidade

`RE_STYLE_PROP` exige forma `chave: valor` — confirmado por teste direto:
`...inputStyle, textAlign: 'center', width: 34` produz só
`[('textAlign','center'),('width','34')]`; o token `...inputStyle` não
corrompe as propriedades vizinhas, mas desaparece sem deixar rastro.
Nenhum mecanismo em `extraction/`/`parsing/`/`core/patterns.py` resolve
`...identificador` de volta ao objeto `const identificador = { ... }`
que ele referencia (confirmado por busca — zero ocorrências de lógica de
spread em todo o pipeline). `get_component_spec("NumInput")` mostra
`type="number"` mas nunca os valores reais de altura/padding/raio que
`inputStyle` carrega.

## Critério de aceite

- No laço de extração de estilo inline (`component_extractor.py`), um
  token `...identificador` dentro do bloco capturado por
  `RE_INLINE_STYLE` dispara uma busca por `const identificador = {` no
  `js` completo (não só na `window` do próprio componente — objetos de
  estilo compartilhados costumam ser definidos uma vez em nível de
  módulo e reusados por vários componentes).
- `parsing.js_parser.find_matching_delimiter` (já público desde C13)
  isola o corpo balanceado do objeto encontrado; as mesmas propriedades
  `chave: valor` já extraídas para o bloco principal são aplicadas a esse
  corpo e mescladas na spec do componente.
- Propriedade definida tanto no objeto referenciado quanto localmente no
  bloco: o valor **local** vence — simplificação documentada (não é a
  ordem exata de merge do JS, que depende da posição textual do
  `...spread` relativa a cada chave; cobre o padrão real observado
  `{...base, overrides}` sem exigir rastreamento posicional).
- Spread sem `const` correspondente encontrável no arquivo: comportamento
  de hoje preservado — o token é ignorado, o resto do bloco continua
  sendo extraído normalmente (nunca lança exceção, nunca corrompe o
  bloco).
- Suíte completa (`pytest tests/unit/ -q`) sem regressão.

## Fora de escopo

- Spread de uma expressão que não seja `const nome = { ... }` literal
  (ex. resultado de função, `...(cond ? a : b)`) — sem evidência de uso
  real nos prototypes de referência.
- Múltiplos níveis de spread encadeado (`const a = {...b}; const c =
  {...a}`) — resolve um nível; encadeamento mais profundo fica para uma
  extensão futura se houver caso real.
