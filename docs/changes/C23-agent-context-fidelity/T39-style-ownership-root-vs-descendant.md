# T39 — Estilo por profundidade de elemento (raiz vs. descendente)

**Arquivos:** `src/design_graph/extraction/plain_html_component_extractor.py`
**Depende de:** —
**Status:** `[x] done`

## Responsabilidade

Impedir que o estilo de um elemento descendente (ex. um `<span>` decorativo
de 7px aninhado dentro de um `<button>`) seja publicado como se fosse o
estilo do componente raiz.

## Nota de implementação — desvio do desenho original da spec

A spec original cogitava estender `StyleEntry` com um dado de profundidade
e filtrar por ele em `mcp/tools.py`. Implementado: `_extract_inline_styles`
simplesmente para de ler depois do **primeiro** `style="..."` encontrado no
snippet (o próprio elemento raiz) — nenhum estilo de descendente chega a
virar `StyleEntry`. Zero campo novo, zero mudança em `core/models.py`/
`mcp/tools.py`, mesmo resultado observável. Mantido assim porque nada
consome hoje um estilo de descendente (a própria spec já marcava reexpor
esse dado como fora de escopo) — carregar um campo `is_root`/`depth` que
nenhum leitor usa seria a exata "abstração sem necessidade real" que a
spec pede para evitar.

## Critério de aceite

- `_extract_inline_styles` lê apenas o primeiro `style="..."` do snippet —
  qualquer atributo de estilo que apareça depois (elemento descendente) é
  ignorado na extração, não apenas escondido na leitura.
- Caso real do `Chip`: `width`/`height`/`border-radius`/`background` do
  `<span class="dot">` interno deixam de aparecer na spec do `Chip` como
  se fossem do `<button>` raiz.
- Componente cujo único estilo capturável está na raiz (nenhum filho
  estilizado) continua com a tabela idêntica à de hoje — teste de
  regressão explícito.
- Suíte completa (`pytest tests/unit/ -q`) sem regressão; guardrail G10
  (`plain_html_component_extractor` não importa de `graph/`/`mcp/`)
  intacta.

## Fora de escopo

- Expor o estilo do elemento descendente em algum outro lugar da resposta
  (ex. `children[].styles`, como a investigação original sugeriu) — este
  task só impede a atribuição errada à raiz; reexpor o dado do filho de
  forma estruturada é uma extensão futura, não parte do fix.
- O caminho de extração de estilo para o pipeline JSX/React
  (`component_extractor.py`) — o gap relatado (`Chip`) foi confirmado no
  caminho `plain_html_component_extractor.py`; se o mesmo padrão existir
  no caminho JSX, é achado para uma task própria, não assumido aqui sem
  confirmação em código.
