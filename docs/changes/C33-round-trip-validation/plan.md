# Plan C33 — Validação round-trip

## Objetivo

Fechar P1 de `spec.md` (só depois do spike documentado ali) sem regredir
C01–C32, mantendo as guardrails de arquitetura.

## Critério de aceite

```bash
pytest tests/unit/ -q
pytest tests/integration/ -q
pytest tests/test_architecture_guardrails.py -q
design-graph "iPede Manager v21.2.html" --force --db /tmp/c33-rebuild.db
design-graph validate --db /tmp/c33-rebuild.db
```

Rebuild real sempre contra `/tmp` — nunca a DB de produção do repositório.

## Ordem de implementação

```
Spike (sem código de produção) — ver spec.md "Spike — resultado"
T71  mcp/tools.py — única task, sem dependências
```

## Validação end-to-end

Rebuild real contra `iPede Manager v21.2.html` (DB descartável em `/tmp`),
comparado ao estado pós-C32 (mesmo arquivo, sem as mudanças deste change):

```
Métrica                     | pós-C32 (baseline) | pós-C33 (final)
-------------------------------|---------------------|------------------
screens / components / tokens  | 14 / 192 / 86       | 14 / 192 / 86 (inalterado)
sections / contains            | 64 / 429            | 64 / 429 (inalterado)
write_errors                   | 0                   | 0
```

Sem mudança de métrica — camada de leitura/API pura, mesmo perfil de C31.

**Testado manualmente contra dado real** (protótipo de referência,
componente `KpiCard`, 15 estilos default reais incluindo ternárias não
resolvidas e valores de tema como `#FFB81C`):

- Reimplementação claramente incompleta (`<div><span>wrong</span></div>`)
  → tool sinaliza corretamente: filho `Sparkline` ausente, 30 estilos
  ausentes (capado em 15 + aviso "+15 mais"), 3 textos ausentes.
- Reimplementação parcialmente correta (inclui `<Sparkline />`, `style`
  com `background`/`alignItems`, texto "PRO") → tool sinaliza
  corretamente: filhos "✅ batem", "PRO" não aparece mais como ausente, e
  os itens remanescentes na lista de "ausentes" são exatamente os que a
  spec original já armazenava como expressão não resolvida (ternárias,
  variantes condicionais) ou como cor Tailwind/CSS custom — a lacuna
  documentada no spec.md, não um falso positivo do fix.

`design-graph validate --db /tmp/c33-rebuild.db`: `status=ok errors=0
warnings=0` (14 screens, 192 components, 64 sections, 86 tokens, 429
CONTAINS) — idêntico a C32, confirmando que este change não toca extração.

Suíte: `pytest tests/unit/ -q` → 1747 passed (10 novos testes: 3 do
extrator de candidato, 7 da tool). `pytest tests/integration/ -q` → 155
passed. `pytest tests/test_architecture_guardrails.py -q` → 22 passed.

## Encerramento do roadmap C25–C33

Este é o último dos 9 change-sets planejados em resposta à auditoria
técnica original (ver artifact "Raio-X do design-graph" e
`docs/changes/C25-write-integrity/spec.md` para o contexto completo). Os 35
achados da auditoria foram endereçados ou explicitamente re-escopados com
justificativa documentada (ver C29 sobre `dark:`/responsivo, C32 sobre
classificação de ícone). Nenhum achado ficou pendente sem decisão
registrada.
