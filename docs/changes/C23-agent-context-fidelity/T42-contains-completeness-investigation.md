# T42 — Spike + fix: completude do CONTAINS em componentes com abas/condicionais

**Arquivos:** `src/design_graph/core/patterns.py`
**Depende de:** —
**Status:** `[x] done`

## Responsabilidade

`get_component_children('BasicTab')` devolve 4 filhos
(`IconBtn, NumInput, SwitchRow, TextInput`) contra pelo menos 12 usados de
fato no JSX real do componente (`Card, Field, Segmented, Chip, Pill,
TextArea, Sel, Btn` entre outros).

## Causa raiz confirmada (spike)

A hipótese líder da spec (CONTAINS computado sobre o JSX pós-sanitização)
**não se confirmou** — `component_extractor.py` já escaneia `window`
(fonte bruto, pré-sanitização) para referências de filho via `RE_JSX_TAG`/
`RE_COMP_REF`, não `jsx_snippet` sanitizado.

Causa real, achada lendo o regex: `RE_JSX_TAG` (`core/patterns.py`) exigia
que o nome do componente viesse **imediatamente** depois de `<`
(`r'<([A-Z][a-zA-Z0-9]{2,})[\s/>]'`). O design system do protótipo usa tag
JSX namespaced (`<K.Chip />`, `<K.Segmented />`, `<K.Field />` — confirmado
no HTML ao vivo capturado na investigação original) — `<K.Chip` nunca
casava, porque depois do primeiro caractere (`K`) vem `.`, fora da classe
de caracteres esperada. `RE_COMP_REF` (heurística por sufixo conhecido:
`Card|Modal|Row|...`) também não cobre esses nomes: `Chip`, `Card`, `Btn`,
`Pill`, `Field`, `Sel`, `Segmented` são exatamente os sufixos da própria
lista ou não estão nela — a regex exige um **prefixo** antes do sufixo
(`[A-Z][a-zA-Z0-9]{2,}` + sufixo), então um nome que É o sufixo inteiro,
sem nada antes, nunca casa.

## Critério de aceite

- `test_namespaced_child_tag_is_captured`
  (`tests/unit/extraction/test_component_extractor.py`) prova a
  subcontagem com uma fixture mínima inline (`<K.Card><K.Field><K.Segmented/></K.Field><K.Chip/></K.Card>`)
  — não foi necessário promover fixture de `audit/`.
- `RE_JSX_TAG` aceita um prefixo de namespace opcional
  (`<K.Chip`, `<Namespace.Sub.Component`) antes do nome PascalCase — o
  prefixo fica fora do grupo de captura, então o `ref` extraído continua
  sendo só `Chip`, nunca `K.Chip` (consistente com o nome já usado em
  `get_component_spec('Chip')` em todo o resto do grafo).
- `test_namespace_prefix_itself_is_not_captured_as_a_child` — o próprio
  namespace (`K`) nunca aparece em `child_refs`.
- Regressão: `test_react_internals_not_in_child_refs` (`<React.Fragment>`)
  continua excluindo `Fragment`/`React` — agora via
  `REACT_INTERNALS` (que já continha `"Fragment"`/`"React"`), não mais por
  o regex simplesmente não casar a tag.
- Suíte completa (`pytest tests/unit/ -q`) sem regressão.

## Fora de escopo

- A lacuna irmã em `RE_COMP_REF` (nome bare que É um dos sufixos
  conhecidos, sem prefixo) — não é o padrão que causava o gap relatado;
  toda a lista de componentes faltando em `BasicTab` era por namespace,
  não por essa heurística. Não tocado para não ampliar o raio de mudança
  de uma regex já historicamente sensível a falso-positivo.
- Expandir CONTAINS para capturar uso de componentes vindos de props
  (`{children}` repassado) — não é o padrão relatado.
- Corrigir T43 (classificação de overlay) — esta task só garante que a
  árvore de filhos esteja completa; montar a tela inteira do overlay é
  responsabilidade de T43, que depende deste resultado.
