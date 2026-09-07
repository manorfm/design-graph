# Spec C40 — Comentário de linha grudando na chave seguinte de um objeto

## Contexto

Achado colateral de C39, documentado lá como "fora de escopo" e corrigido
agora, a pedido do usuário, imediatamente depois.

## Problema

`get_component_data("Icon")` contra o `toToggle v2.6` real devolvia uma
entrada com a chave `"// custom below\n  key"` em vez de `"key"`. Fonte
real:

```js
const ICONS = {
  ...
  toggle: null, // custom below
  key: "M21 2l-2 2...",
  ...
};
```

Causa raiz: `split_top_level`/`iter_object_literal_pairs`
(`parsing/js_parser.py`) — usados por `parse_object_literal_props`
(estilos), `module_text_extractor.py` e `module_data_extractor.py` (C39)
— nunca removiam comentário de linha (`//...`) antes de dividir por
vírgula. O split em `toggle: null, // custom below\n  key: "..."` só acha
a próxima vírgula DEPOIS do valor de `key`, então o segmento inteiro
(`// custom below\n  key: "..."`) vira um par só; `iter_object_literal_pairs`
parte no primeiro `:`, que é o de `key:` — o comentário sobra grudado como
prefixo da chave.

## Solução

Nova função privada `_strip_comments(text)` em `parsing/js_parser.py`,
chamada no início de `split_top_level` (o único ponto de entrada
compartilhado pelos três consumidores acima — corrige todos de uma vez).
Reaproveita `JavaScriptLexicalView.analyze()` (já existente, já usada para
distinguir string real de comentário/texto ignorável em outro lugar do
arquivo) em vez de reimplementar rastreio de aspas: cada `ignored_range`
que abre com `/` é comentário (`//` ou `/* */`) e é apagado (substituído
por espaços, preservando posição/tamanho); um range que abre com aspas é
string real e fica intocado — uma URL como `href: "https://exemplo.com"`
nunca é confundida com início de comentário.

## Verificação

```
pytest tests/unit -q                              → 1931 passed
pytest tests/unit tests/integration \
       tests/test_architecture_guardrails.py -q   → 2118 passed
design-graph "toToggle v2.6.html" --force
design-graph validate --db ".../toToggle v2.6.db"  → status=ok errors=0 warnings=0
```

Confirmado contra o `toToggle v2.6` real: `get_component_data("Icon")`
mostra `key: M21 2l-2 2...` sem o comentário grudado; `"custom below"` não
aparece mais em lugar nenhum da saída.

## Fora de escopo

- Comentário de linha/bloco em qualquer lugar FORA de um literal de
  objeto/array (ex. dentro do corpo de uma função) — `split_top_level` só
  é chamado sobre texto já isolado de um literal; não há evidência de que
  outro consumidor precise da mesma limpeza.
