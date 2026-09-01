# Spec C37 — Detecção estrutural ignora padding/margin resolvido por classe CSS

## Contexto

Achado ao verificar, com o mesmo agente externo (projeto `toToggle`), se o
fix de C36 tinha propagado para outras telas além de `HistoryView`. Relato:
`get_screen("UsersView")` devolve `Seções: 0`, mesmo a tela tendo um bloco
`<div className="page"><div className="page-head">...` com `.page-title`,
`.page-desc` e um `<span className="chip">`/`.badge` reais — nenhum deles
nunca vira seção nem componente, então seus estilos ficam inacessíveis por
qualquer via (mesma classe de problema de P3/C36, causa raiz diferente).

## Causa raiz confirmada

`section_extractor._detect_by_structure` (Strategy 2, o fallback estrutural)
só reconhece padding/margin **literal** via `_PADDING_RE`:

```python
_PADDING_RE = re.compile(r'style=\{\{[^}]*(?:padding|margin)\s*:\s*["\']?(\d+)px')
```

Isso casa `style={{padding: 24}}` mas nunca um valor que só existe na
stylesheet via `className`. Confirmado contra `toToggle v2.3.html` real
(`extract_css_rules` sobre o CSS decodificado):

```
.page       { padding: 26px var(--pad) 60px; ... }
.page-head  { margin-bottom: 26px; ... }
.chip       { padding: 0 13px; ... }
.empty      { padding: 70px 20px; ... }
```

Todos ultrapassam o limiar de 16px (`_STRUCTURAL_PADDING_THRESHOLD`), mas
como nenhum aparece como `style={{}}` inline — o próprio `section_extractor`
já documenta em três lugares diferentes que este prototype "estiliza
containers via classes CSS, não `style={{}}`" — a Strategy 2 nunca os vê.
`UsersView` não tem comentários de seção (Strategy 1 não casa) nem um
`.map()` de tag minúscula sem componente nomeado (Strategy 3 não se
aplica — `UserRow` já é um componente nomeado de verdade), então a tela cai
direto para "0 seções", mesmo tendo chrome real e substancial.

## Fix

`_detect_by_structure` ganha uma segunda fonte de candidatos, ao lado da
existente (`_literal_padding_candidates`, extraída sem mudança de
comportamento): `_resolved_class_padding_candidates`, que localiza
`<div className="...">` e resolve as classes via `resolve_classes`
(já usado por `_resolve_section_element_styles`) — um `<div>` cujo
`padding`/`margin`/`padding-*`/`margin-*` resolvido (estado `default`)
tem algum token `Npx` ≥ 16 qualifica exatamente como um candidato literal
qualificaria. As duas listas de candidatos são combinadas e ordenadas por
posição antes do dedup/construção de seção já existentes — sem duplicar
essa lógica.

## Fora de escopo

- Resolver a mesma questão para Tailwind color utilities ou outras
  propriedades fora de padding/margin — o limiar estrutural sempre foi só
  sobre padding/margin como sinal de "container visualmente separado".
- `.chip` dentro de `<span className="badge">{...}</span>` no exemplo real
  de `UsersView` — o `chip` citado no relato original mora em telas
  diferentes (`ApprovalStatusChip` em `ApprovalsView`); o `.badge` real de
  `UsersView` é outra classe. Este fix resolve a detecção da SEÇÃO ao redor
  (`.page`/`.page-head`), o que já torna `.page-title`/`.page-desc`/
  `.badge` alcançáveis via `get_section`/`get_full_styles` uma vez que a
  seção existe — não precisa de tratamento especial por classe.
