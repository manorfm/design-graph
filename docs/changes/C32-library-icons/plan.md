# Plan C32 — Referências externas permanentemente não resolvidas

## Objetivo

Fechar P1 de `spec.md` (versão revisada, ver "Investigação e re-escopo")
sem regredir C01–C31, mantendo as guardrails de arquitetura.

## Critério de aceite

```bash
pytest tests/unit/ -q
pytest tests/integration/ -q
pytest tests/test_architecture_guardrails.py -q
design-graph "iPede Manager v21.2.html" --force --db /tmp/c32-rebuild.db
design-graph validate --db /tmp/c32-rebuild.db
```

Rebuild real sempre contra `/tmp` — nunca a DB de produção do repositório.

## Ordem de implementação

```
T70  graph/writer.py (flush_pending_contains) — única task, sem dependências
```

## Validação end-to-end

Rebuild real contra `iPede Manager v21.2.html` (DB descartável em `/tmp`),
comparado ao estado pós-C31 (mesmo arquivo, sem as mudanças deste change):

```
Métrica                     | pós-C31 (baseline) | pós-C32 (final)
-------------------------------|---------------------|------------------
screens / tokens                | 14 / 86             | 14 / 86 (inalterado)
sections                        | 64                  | 64 (inalterado)
components                      | 177                 | 192 (+15)
unresolved_components           | 1                   | 16 (+15)
contains_rels                   | 412                 | 429 (+17)
write_errors                    | 0                   | 0
```

Leitura: 15 referências antes completamente invisíveis no grafo
(`KField`, `KSel`, `KTextInput`, `MenuItem`, `PromoIcon`, entre outras)
agora existem como componentes `UNRESOLVED` alcançáveis via
`get_component_children` do pai — exatamente o tipo de referência que a
auditoria original apontou como perdida, só que o ponto real de perda era
mais grave (desaparecimento total, não apenas falta de dado visual).
`contains_rels` sobe mais que `components` (+17 vs +15) porque algumas
dessas referências externas são usadas por mais de um componente pai.

`design-graph validate --db /tmp/c32-rebuild.db`: `status=ok errors=0
warnings=0` (14 screens, 192 components, 64 sections, 86 tokens, 429
CONTAINS) — nenhum erro novo introduzido pelos 15 shells adicionais
(`validate` já tolera componentes sem referência de tela, categoria
"[INFO] component(s) have no screen references").

Suíte: `pytest tests/unit/ -q` → 1737 passed (5 novos testes). `pytest
tests/integration/ -q` → 155 passed. `pytest
tests/test_architecture_guardrails.py -q` → 22 passed.
