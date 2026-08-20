# T41 — Honestidade de `get_full_jsx` sobre snippet sanitizado

**Arquivos:** `src/design_graph/core/models.py` (novo `JsxSnippet`),
`src/design_graph/mcp/tools.py`
**Depende de:** T38 (vocabulário de marcadores reconhecido deve refletir o
formato de handler/estilo que T38 deixa)
**Status:** `[x] done`

## Responsabilidade

`get_full_jsx` hoje rotula qualquer resposta como `"# JSX completo"`
incondicionalmente, mesmo quando o snippet armazenado no grafo já passou
por `sanitize_jsx` e contém marcadores (`={[handler]}`, `.[fn]`,
`{[list:…]}`, `{[conditional:…]}`, `{[either:…]}`, bloco de estilo
colapsado — `, ... }}`). Isso não é um corte acontecendo na resposta do tool — é um
fato sobre o dado armazenado que o tool nunca verifica antes de rotular.
`JsxSnippet` (mesmo espírito de `CappedJsx`, T27/C14) carrega esse fato no
próprio valor.

## Nota de implementação

`JsxMarkerKind` só nomeia list/conditional/either — os demais marcadores
(`={[handler]}`, `.[fn]`, sufixo `, ... }}` de bloco de estilo colapsado,
`{...}` de expressão genérica) não tinham nenhuma constante compartilhada;
cada um era um literal solto dentro de `jsx_sanitizer.py`. Para
`JsxSnippet.was_sanitized` não duplicar esse vocabulário (dois lugares
decidindo separadamente "o que é um marcador"), as quatro constantes
(`JSX_HANDLER_MARKER`, `JSX_ARROW_FN_MARKER`,
`JSX_STYLE_BLOCK_COLLAPSE_SUFFIX`, `JSX_BARE_EXPRESSION_MARKER`) passaram a
viver em `core/models.py`, ao lado de `JsxMarkerKind`; `jsx_sanitizer.py`
foi atualizado para produzir os marcadores a partir delas em vez de
literais hardcoded — quem produz e quem detecta leem da mesma fonte.

## Critério de aceite

- `JsxSnippet(str)` em `core/models.py`: `.was_sanitized` (bool, verdadeiro
  se qualquer marcador do vocabulário conhecido está presente) e
  `.markers_found` (lista dos tipos de marcador encontrados, para uso em
  mensagem de diagnóstico).
- `ToolDispatcher.get_full_jsx` (`mcp/tools.py`) envolve o retorno de
  `reader.get_full_jsx` em `JsxSnippet` e decide o cabeçalho/aviso a
  partir de `.was_sanitized` — nunca mais monta `"# JSX completo"`
  incondicionalmente.
- Snippet sem nenhum marcador continua exatamente como hoje (sem aviso
  falso-positivo) — teste de regressão explícito.
- Snippet com marcador ganha aviso explícito no texto devolvido, nomeando
  que o corte aconteceu na extração (não é recuperável chamando o próprio
  `get_full_jsx` de novo) — evita o loop relatado na investigação original
  (4 tentativas do mesmo agente realinhando a mesma aba).
- Nenhuma coluna nova persistida no schema Kuzu — `.was_sanitized` é
  computado em tempo de leitura sobre o snippet já armazenado (ver
  `spec.md` → Boas práticas, YAGNI explícito).
- Suíte completa (`pytest tests/unit/ -q`) sem regressão.

## Fora de escopo

- Recuperar o JSX original pré-sanitização — não existe mais no grafo
  (`sanitize_jsx` roda na extração, o texto original não é persistido);
  isso exigiria mudar o que é armazenado, fora do escopo desta task.
- Aplicar `JsxSnippet` em `get_screen_full`/`get_component_spec` — esses
  já usam `CappedJsx` com aviso próprio (`recoverable_via`); nenhum gap
  relatado ali.
