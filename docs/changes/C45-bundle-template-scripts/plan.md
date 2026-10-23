# Plan C45 — Bundles React com o código no template (iPede KDS)

> Investigação de 2026-10-23 sobre `../prototipos/iPede KDS.html` (1,7 MB).

## 1. Sintoma

`design-graph "iPede KDS.html"` → `screens=0 comps=0 tokens=31` (só os tokens
do CSS). O arquivo tem 21 funções de nível superior e 31 `onClick`.

## 2. Causa

Mesmo bundler externo dos outros protótipos React, mas **um terceiro layout**:

| Layout | Onde está o código do protótipo | Lido? |
|---|---|---|
| Manager / Anamnese | entrada do `__bundler/manifest` (mime script) | sim |
| Standalone v4 | entrada do manifest, referenciada por `<script type="text/babel" src=uuid>` | sim |
| **KDS** | **`<script type="text/babel">` inline dentro do `__bundler/template`** | **não** |

`source_loader._read_scripts` trata o template (string JSON) só como
`inner_html`. O `js` que sobrava (16 782 chars) era o **script desempacotador
do próprio bundler** (`DOMContentLoaded … __bundler/manifest`), lido como se
fosse o protótipo. React/ReactDOM/Babel vinham do manifest e eram corretamente
excluídos como infraestrutura.

## 3. É um adapter novo? Não.

- `registry.CAPTURES` escolhe por **formato do protótipo** (DC canvas vs HTML).
  O KDS é React em HTML: `HtmlPrototypeCapture` já o reconhece e todo o
  restante (js_parser, component/screen/section extractors, tokens, CSS) serve.
- O defeito é só na **etapa de carga** (`source_loader`), que decide *quais
  textos são código*. Um adapter duplicaria extração inteira para corrigir uma
  linha de roteamento e criaria dois caminhos a manter.
- O mesmo defeito escondia código em outro arquivo: `iPede Prototype v5.4`
  passou de `screens=0 comps=70` para `screens=1 comps=76`.

Portanto: **variante de layout dentro do loader**, atrás do mesmo contrato
(`RawSources`). Nada muda para DC canvas, MCP, graph ou pipeline.

## 4. Mudança (já aplicada, não commitada)

`capture/html_prototype/parsing/source_loader.py`
1. `_inline_scripts(inner_html)`: blocos `<script>` sem `src` do template
   desempacotado entram no `js` (ignora `[`/`{`/`"` = dados do bundler).
2. `_is_bundler_runtime(text)`: descarta o script desempacotador (`__bundler`)
   tanto dos scripts da página quanto do template.

Teste: `test_bundled_react_extraction.py::test_code_inside_the_unpacked_template_is_read_and_the_unpacker_is_not`.

## 5. Verificação (feita)

| Protótipo | Antes | Depois |
|---|---|---|
| iPede KDS | 0 telas / 0 comps | 4 telas / 13 comps / 42 tokens |
| iPede Prototype v5.4 | 0 / 70 | 1 / 76 |
| Manager v21.2, Anamnese v3, KDS v4 Standalone | — | idênticos |
| Suíte completa | — | 2642 passed |

## 6. Pendências (cada uma = task própria, só se confirmadas)

- **T-a** Conferir KDS contra o fonte: 13 componentes de ~21 funções. Telas
  (App, KanbanView, FocusView, MesaView) e `Column` aninhado parecem certos;
  validar `SourceTag`/`UrgencyBar`/`Toggle`/`Slider` e se `SEED`/`STATUS_CFG`
  aparecem como dados referenciados (`get_full aspect=data`).
- **T-b** `Interactions: 0`: o capture só registra hover/focus por mutação de
  `style`; os 31 `onClick` (avançar, cancelar, recall, trocar visão) não viram
  interação. É lacuna de modelo, não do loader — avaliar à parte (C12/C13).
- **T-c** KDS v4 Standalone: `screens=0 comps=5` — o app é um módulo de 18 KB
  referenciado por `src`; confirmar se é só um módulo de dados ou se há
  código não alcançado.
- **T-d** Teste de regressão com fixture mínima do layout KDS em
  `tests/…/test_real_prototypes` (padrão de d07a0f4), sem commitar o arquivo real.
