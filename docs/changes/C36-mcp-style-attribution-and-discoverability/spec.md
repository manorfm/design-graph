# Spec C36 — Atribuição de estilo por seletor + descoberta de classes compartilhadas

## Contexto

Investigação disparada por um relato de outro agente (sessão externa, projeto
consumidor `toToggle`), verificado contra este repositório usando o doc real
`toToggle` (`toToggle v2.3.html`, já indexado). Cinco problemas confirmados,
reproduzidos linha a linha nas camadas `extraction/`, `graph/`, `parsing/` e
`mcp/`.

## Problemas confirmados

### P1 — `get_section`/`get_screen_full` achatam estilos de seletores diferentes num único array

`get_section(screen="HistoryView", section="Audit item")` devolve um array
plano (`display:grid`, `flex-direction:column`, `padding:4px 0`, ...) sem
dizer que cada propriedade pertence a um seletor diferente dentro da seção
(`.audit-item`, `.audit-rail`, `.audit-dot`...). Causa raiz:
`section_extractor._resolve_section_class_styles` já recebe `StyleEntry`
corretamente atribuído por classe (via `resolve_classes`, que preserva
`entry.element = "class:X"`), mas colapsa tudo em `dict[property, value]`
antes de devolver — descartando `entry.element` duas vezes (na extração e de
novo na escrita, `StyleEntry.for_section` força `element=section_id`).

**Bug irmão, mais grave, achado durante a investigação**: `GraphWriter`
pula a criação da EDGE (`HAS_STYLE`/`SECTION_HAS_STYLE`), não só do nó,
quando um `Style` de classe CSS compartilhada já foi inserido por outro
dono (`if style.id in self._inserted_style_ids: continue`). Como o id de
um `StyleEntry.from_css_class` é determinístico por classe+propriedade
(não inclui o dono), qualquer classe CSS reusada por ≥2 componentes/seções
em QUALQUER prototype já construído por este projeto perde silenciosamente
a relação para o segundo dono em diante.

### P2 — Sem `get_full_jsx`-equivalente para estilos

Truncamento acontece só na camada de apresentação (`mcp/tools.py`, fatias
`[:12]`/`[:8]`/`[:6]`) — o dado completo já está no reader, só não há
chamada que peça "sem corte".

### P3 — Classes CSS compartilhadas sem componente React nomeado são invisíveis

`get_component_spec("page-title")`/`search("page-title")` não encontram
nada, mesmo a classe sendo usada em 5 telas — porque nem `search` nem
`get_component_spec` sabem procurar por `Style.element` (`class:X`),
só por nome de nó `Component`.

### P4 — `get_full_jsx("App")` devolve só um branch, não o componente inteiro

`extract_return_block` usa `re.search()` — pega o PRIMEIRO `return` que
casa a regex na janela inteira da função. Um componente com múltiplos
`if (cond) return <X/>;` (guard clauses) antes do `return` "default" perde
todos os outros branches, incluindo o que de fato renderiza a UI principal.

### P5 — `get_screen_layout` não reflete seções com markup inline

`get_screen_layout` só consulta `Screen -[:USES_COMPONENT]-> Component`,
nunca `Section`. Uma tela cujo item de lista nunca foi fatorado em
componente nomeado (mesma causa-raiz de P1/P3) fica sem nenhum perfil de
layout, mesmo tendo `display:grid`/`flex-direction` reais no grafo.

## Fora de escopo

- Fuzzy-match de nome de componente "sequestrando" uma consulta por classe
  genérica antes de tentar o fallback de classe (ex.: `get_component_spec
  ("chip")` acha `ApprovalStatusChip` por substring antes de checarmos se
  "chip" também é uma classe CSS real usada em outra tela) — precisão do
  fuzzy-match é um problema pré-existente, não introduzido nem alargado por
  esta mudança. Documentado, não corrigido aqui.
- Atribuição por seletor de estilos `style={{}}` literais dentro de uma
  seção — sem uma travessia de DOM real não dá pra saber a qual elemento
  aninhado um objeto de estilo literal pertence (diferente de `className`,
  que já carrega a identidade do seletor). Continuam atribuídos à seção
  como um todo, exatamente como hoje.
- className resolvido dinamicamente (`className={"audit-dot " + (AUDIT_DOT
  [e.type] || "")}`, confirmado no `toToggle` real) — `RE_CLASS_NAME` só
  captura `className="literal"` estático, então essa classe nunca entra em
  `element_styles` nem em `list_shared_style_classes`. Causa raiz diferente
  de P1/P3 (é extração de className, não atribuição/descoberta do que já foi
  extraído) — `get_component_spec("audit-dot")` continua "não encontrado"
  mesmo depois desta mudança. Fora de escopo aqui.
- Guard clause cujo `return` está dentro de bloco próprio
  (`if (cond) { return X; }`) — mesma classe de limitação que C21 já aceita
  para condicionais dentro de uma árvore JSX, agora também documentada para
  múltiplos `return` no corpo da função.
