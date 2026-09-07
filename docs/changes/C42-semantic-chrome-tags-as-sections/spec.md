# Spec C42 — `<aside>`/`<nav>`/`<header>`/`<footer>` como seção + nome por `className`

## Contexto

Pergunta direta do usuário depois de C38 (que tornou `App` navegável como
tela): se as seções de `App` saem nomeadas `Section1`..`Section7`, como um
agente encontra "a sidebar" quando pedem pra atualizar ela — por busca ou
por `get_section(screen="App", section="sidebar")`? Investigação mostrou
que não era só um problema de nome — a sidebar real do `toToggle` nunca
virava seção nenhuma.

## Problemas confirmados

### P1 — Tag semântica nunca é candidata a seção

O fallback estrutural (`_detect_by_structure`) só reconhecia `<div>` como
candidato, exigindo padding próprio (literal ou resolvido por classe CSS)
pra qualificar. A sidebar real do `toToggle` é:

```jsx
<aside className={"sidebar" + (navOpen ? " open" : "")} ...>
```

Um `<aside>` nunca era varrido como candidato (regex de abertura só
buscava `<div\b`), então a sidebar inteira ficava dissolvida dentro do
JSX geral de `App`, sem seção própria — `get_section`/`search` nunca
tinham como achá-la.

### P2 — Mesmo quando a tag é `<div>`, o nome vinha do primeiro texto, não do `className`

A topbar real (`<div className="topbar">`) já virava seção — mas com o
nome "Menu" (primeiro texto visível dentro do bloco), não "Topbar". O
`className` já era o nome literal que o desenvolvedor deu pra região,
mais confiável que "o que por acaso aparece primeiro visualmente".

## Solução

- `_semantic_chrome_candidates`: nova fonte de candidato em
  `_detect_by_structure`, reconhecendo `<aside>`, `<nav>`, `<header>`,
  `<footer>` **sem exigir padding próprio** — ao contrário de um `<div>`
  genérico (que precisa de sinal real pra não qualificar todo container),
  uma tag semântica dessas já é sinal suficiente de "isto é chrome de
  página" pela própria convenção HTML5. `<main>`/`<section>` ficam de fora
  deliberadamente (ver "Fora de escopo").
- `_find_balanced_tag_end`: generalização de `_find_balanced_div_end`
  (que virou um wrapper fino) pra fechar o bloco de qualquer tag, não só
  `<div>`.
- `_class_based_name`: nome derivado do `className` da própria tag raiz do
  bloco — tolerante tanto a `className="sidebar"` (literal) quanto a
  `className={"sidebar" + (cond ? " open" : "")}` (expressão — só a parte
  literal do começo é usada). Passa a ter prioridade sobre "primeiro texto
  visível", pra `<div>` e pras tags semânticas novas igualmente.

## Verificação

```
pytest tests/unit -q                              → 1950 passed
pytest tests/unit tests/integration \
       tests/test_architecture_guardrails.py -q   → 2127 passed
design-graph "toToggle v2.6.html" --force
design-graph validate --db ".../toToggle v2.6.db"  → status=ok errors=0 warnings=0
```

Confirmado contra o `toToggle v2.6` real — `App` agora tem, entre suas
seções: `Sidebar` (o `<aside>` real, antes invisível), `Topbar` (antes
"Menu"), `Page` (antes "Section4"), `Skey warn` ×2 (antes "Section5"/
"Section6"), `Toast` (antes "Section7"). `get_section(screen="App",
section="sidebar")` devolve a seção real (estilos de `.avatar`, `.brand`,
`.brand-mark`, `.brand-name`, etc.) — antes retornava "Seção não
encontrada" porque a seção nunca existiu.

## Fora de escopo

- `<main>`/`<section>` como candidatos automáticos — ambos são comuns
  como wrapper puramente estrutural sem região distinta própria, e
  `<section>` corre o risco de casar com o corpo inteiro de quase toda
  tela. Regra mais estreita fica pra uma atualização futura, se aparecer
  evidência real de necessidade.
- Resolução de estilo CSS-por-classe pra `className={"literal" + expr}` —
  `RE_CLASS_NAME` (usado por `_resolve_section_element_styles` e outros
  pontos de resolução de estilo) só reconhece `className="literal"`
  puro, sem chave antes da aspa. A sidebar detectada por este change tem
  seus estilos próprios via classes de FILHOS (`.avatar`, `.brand`, etc.,
  todos literais) capturados normalmente; só o `.sidebar` do próprio
  `<aside>` (uma classe dentro de uma expressão) fica sem resolução de
  estilo — achado colateral, registrado, não corrigido aqui.
