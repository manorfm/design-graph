# Spec C14 — Extraction: classificação de texto de tooltip (title/aria-label/alt)

## Problema

Elementos com `title="..."`, `aria-label="..."` ou `alt="..."` carregam texto
descritivo que **não faz parte do conteúdo sempre visível** — é revelado no
hover (tooltip) ou lido só por leitores de tela. Em botões só-com-ícone, esse
atributo é o **único** sinal textual do que o elemento faz:

```jsx
<button onClick={onClose} title="Fechar" aria-label="Fechar modal">
  <XIcon />
</button>
```

Antes desta change, `RE_UI_STRING` (a regex genérica de captura de texto)
já pegava esses valores incidentalmente — mas como qualquer outra string
maiúscula entre aspas, sem diferenciar de conteúdo visível. Resultado: no
grafo, `"Fechar"` aparecia com `text_type="label"`, indistinguível de um
`<label>Fechar</label>` visível na tela. Um agente perguntando "o que esse
botão mostra visualmente?" não tinha como saber que só existe um ícone e o
texto só aparece no hover.

### Impacto medido

No prototype `iPede Manager v15.1.html`: **143 valores únicos** de `title=`
(mais alguns `aria-label=`/`alt=`), todos previamente capturados sob o
`text_type` genérico `"label"` (verificado contra o grafo real antes desta
change — `"Abrir perfil da conta"`, `"Adicionar Componente"`, `"Fechar"`
apareciam como `label`).

## Solução

Nova regex `RE_TOOLTIP_TEXT` (`patterns.py`) captura `title=`/`aria-label=`/
`alt=`. Novo membro de enum `TextType.TOOLTIP`. A extração roda **antes** do
laço genérico `RE_UI_STRING` em `extract_component` — como o id de
`TextEntry` é derivado de `(source, content)` (não do `text_type`), a
primeira classificação a inserir um dado texto "vence" o dedup; rodar o
laço de tooltip antes garante que texto de `title`/`aria-label` fique como
`tooltip`, não seja reclassificado como `label`/`description` genérico.

## Invariantes

- Texto igual capturado por `title`/`aria-label` em elementos diferentes do
  mesmo componente continua gerando entradas distintas (id inclui `source`).
- Nenhuma duplicação: o mesmo texto nunca aparece duas vezes com
  `text_type` diferente para o mesmo componente.
- Comportamento anterior preservado para todo texto que não vem de
  `title`/`aria-label`/`alt` — nenhuma regressão nos testes existentes de
  `heading`/`button`/`label`/`placeholder`/`description`.

## Fora de escopo

- Diferenciar `title` (tooltip via hover) de `aria-label` (só leitor de
  tela, nunca visível) de `alt` (texto alternativo de imagem) — os três
  compartilham o mesmo `text_type="tooltip"` nesta change. Seriam 3
  categorias genuinamente distintas para um agente que precisasse simular
  comportamento de acessibilidade, mas a contagem de `alt`/`aria-label`
  neste prototype é baixa (5 no total) — não justificou 3 enums separados
  agora.

## Arquivos afetados

| Arquivo | Mudança |
|---|---|
| `src/design_graph/core/patterns.py` | `RE_TOOLTIP_TEXT` |
| `src/design_graph/core/models.py` | `TextType.TOOLTIP` |
| `src/design_graph/extraction/component_extractor.py` | novo laço de extração, antes de `RE_UI_STRING` |
| `tests/unit/core/test_models.py` | `TestTextType.test_members` atualizado |
| `tests/unit/extraction/test_component_extractor.py` | `TestTooltipTextExtraction` |
