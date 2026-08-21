# T44 — CSS de `<style>` estático em `inner_html` (bundled_react)

**Arquivos:** `src/design_graph/parsing/source_loader.py`
**Depende de:** —
**Status:** `[x] done`

## Responsabilidade

Para prototypes `bundled_react` (o formato do próprio iPede Manager),
`sources.css` fica vazio mesmo quando o `<style>` estático embutido no
HTML da página (`sources.inner_html`) contém regras reais — confirmado
por execução direta de `source_loader.load()` contra `iPede Manager
v15.1.html`: `css` = 0 bytes, `inner_html` = 4692 bytes com um `<style>`
contendo `.pulse-dot`, `.icon-btn`, `input:focus, select:focus,
textarea:focus { ... }`. `_extract_bundled_react` só coleta CSS de
entradas do bundle JSON com `mime` contendo `"css"`; nunca examina o
`inner_html` que ele mesmo já resolve. Log do build real confirma o
efeito: `"pipeline: resolved 0 CSS class rules from stylesheet"` — zero
regras de qualquer tipo, não só a de foco relatada no log original.

## Critério de aceite

- Depois de `inner_html` ser resolvido em `_extract_bundled_react`
  (incluindo o fallback `inner_html = str(soup)` quando nenhuma entrada
  de bundle fornece HTML), a função passa por
  `BeautifulSoup(inner_html, "html.parser").find_all("style")` e soma o
  texto de cada `<style>` encontrado a `css_parts` antes do
  `"\n".join(css_parts)` final.
- `source_loader.load()` contra `iPede Manager v15.1.html` real produz
  `sources.css` não-vazio contendo `input:focus` e `.pulse-dot`.
- Regressão: um bundle cuja entrada JSON já tem `mime` contendo `"css"`
  continua contribuindo — a nova fonte só soma a `css_parts`, nunca
  substitui o que o scan de entradas já preencheu.
- Suíte completa (`pytest tests/unit/ -q`) sem regressão; guardrail G1
  (`parsing/` não importa de `extraction/`/`graph/`/`mcp/`) intacto —
  `BeautifulSoup` já é dependência do próprio `source_loader.py`
  (`_extract_plain` já a usa para o mesmo propósito).

## Fora de escopo

- CSS-in-JS via `styled-components`/`emotion`/outro padrão de template
  literal que não termine renderizado como um `<style>` real no HTML —
  não encontrado nos prototypes de referência; sem evidência, fora.
- `_extract_plain` (formatos `plain_html`/`tailwind`) — já faz a extração
  equivalente para seu próprio caminho; não tocado.
