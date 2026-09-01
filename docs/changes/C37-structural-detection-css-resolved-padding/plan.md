# Plan C37

## Critério de aceite

```bash
pytest tests/unit -q
pytest tests/integration -q
pytest tests/test_architecture_guardrails.py -q
design-graph "toToggle v2.3.html" --force --db /tmp/c37-rebuild-totoggle.db
design-graph validate --db /tmp/c37-rebuild-totoggle.db
```

## Implementação (TDD red/green)

`extraction/section_extractor.py`:

- `_literal_padding_candidates(window)` — extraída de `_detect_by_structure`
  sem mudança de comportamento (mesma regex `_PADDING_RE`, mesmo scan).
- `_resolved_class_padding_candidates(window, rule_map)` — nova. Localiza
  `<div className="...">` via `_DIV_CLASS_RE`, resolve as classes com
  `resolve_classes` (já usado por `_resolve_section_element_styles`), e
  qualifica quando algum `StyleEntry` default tem `property` começando em
  `"padding"`/`"margin"` (cobre shorthand e longhand: `padding`,
  `padding-top`, `margin-bottom`...) com `_max_px(value) >= 16` — `_max_px`
  extrai o maior token `Npx` de um valor shorthand (`26px var(--pad) 60px`).
- `_detect_by_structure` combina as duas listas de candidatos, ordena por
  posição, e segue o dedup/construção de seção já existente sem duplicar
  essa lógica.

Também corrigido no mesmo commit lógico: `get_full_styles(name=X)` não
tinha o fallback para `find_styles_by_class` que `get_component_spec(name=X)`
já tinha (C36 P3) — `get_full_styles(name="audit-av")` respondia "não
encontrado" mesmo com a classe real e resolvida no grafo. Mesma correção
aplicada em `mcp/tools.py`.

## Achado lateral corrigido junto (reportado pelo mesmo agente externo)

`get_full_styles(name=X)` sem o fallback de classe CSS compartilhada (ver
acima) — não é uma nova causa raiz, é o mesmo fix de C36 P3 que não tinha
sido replicado no tool "full" irmão.

## Validação end-to-end — executada em 2026-09-01

Causa raiz confirmada contra `toToggle v2.3.html` real antes de escrever
qualquer teste: `extract_css_rules` sobre o CSS decodificado mostra
`.page{padding:26px var(--pad) 60px}`, `.page-head{margin-bottom:26px}`,
`.chip{padding:0 13px}`, `.empty{padding:70px 20px}` — todos acima do
limiar de 16px, nenhum inline.

```
pytest tests/ -q                                        → 2050 passed
design-graph "toToggle v2.3.html" --force --db /tmp/verify-totoggle.db
  → Sections: 5 → 14, SecStyles: 154 → 637
design-graph validate --db /tmp/verify-totoggle.db      → status=ok errors=0 warnings=0
```

Verificado manualmente, exatamente os casos que o relato original apontou
como ainda quebrados após C36:

- `get_screen("UsersView")` — antes "Seções: 0"; agora "Seções: 1", com
  `.page`, `.page-head`, `.page-title`, `.page-desc`, `.badge`, `.btn`,
  `.field-hint` todos com estilos reais e atribuídos por seletor.
- `get_full_styles(name="audit-av")` — antes "não encontrado" (só
  `get_component_spec` tinha o fallback de classe); agora devolve a lista
  completa (`width: 18px`, `height: 18px`, etc.).

Nota: o nome da seção detectada ficou uma frase da JSX ("Root cria usuários
em qualquer time.") em vez de algo como "Header" — usa a mesma heurística
de nome já existente para Strategy 2 (primeiro texto UI encontrado no
bloco); não é uma regressão nem estava no escopo deste fix, mas é uma
melhoria de nome cosmética candidata a um change futuro se incomodar na
prática.
