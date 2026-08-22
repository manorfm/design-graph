# Plan C31 — Expansão da API MCP

## Objetivo

Fechar P1–P3 de `spec.md` sem regredir C01–C30, mantendo as guardrails de
arquitetura. Depende de C30 (`order_index` já precisa existir).

## Critério de aceite

```bash
pytest tests/unit/ -q
pytest tests/integration/ -q
pytest tests/test_architecture_guardrails.py -q
design-graph "iPede Manager v21.2.html" --force --db /tmp/c31-rebuild.db --diff
design-graph validate --db /tmp/c31-rebuild.db
```

Rebuild real sempre contra `/tmp` — nunca a DB de produção do repositório.

## Ordem de implementação

```
T67  graph/reader.py + mcp/tools.py                              (P1) — depende de C30
T68  mcp/tools.py                                                 (P2) — independente
T69  core/models.py + pipeline/state.py + pipeline/coordinator.py
     + graph/reader.py + mcp/server.py + mcp/tools.py              (P3) — independente
```

T67 e T68/T69 podem rodar em paralelo entre si; T67 depende só de C30, já
concluído.

## Validação end-to-end

Rebuild real contra `iPede Manager v21.2.html` (DB descartável em `/tmp`),
comparado ao estado pós-C30 (mesmo arquivo, sem as mudanças deste change):

```
Métrica                     | pós-C30 (baseline) | pós-C31 (final)
-------------------------------|---------------------|------------------
screens / components / tokens  | 14 / 177 / 86       | 14 / 177 / 86 (inalterado)
sections / contains            | 64 / 412            | 64 / 412 (inalterado)
write_errors                   | 0                   | 0
```

Nenhuma métrica de extração muda — as três tasks são camada de leitura/API,
não de extração.

**get_component_full testado contra componente real com múltiplos níveis**
(`BasicTab`, protótipo de referência): raiz + 15 descendentes (16
componentes na árvore), incluindo um neto (`Btn → Spinner`, 2º nível),
cada um com seus próprios estilos por estado — confirmado que `Btn` traz
`default` e `hover`. Resposta Markdown inclui o aviso de `truncated_fields`
da raiz corretamente.

**list_components**: sem dado real no protótipo de referência que exceda
100 componentes (tem 177 no total, mas cada `comp_type` filtrado fica bem
abaixo do limite) — cobertura real vem do teste sintético
(`_ManyComponentsReader`, 150 componentes) que reproduz exatamente o
cenário de excesso.

**get_build_diff testado end-to-end com dado real**: rebuild com `--force`
sempre limpa o state anterior antes de calcular o diff (comportamento
pré-existente da CLI, não alterado por este change —
`cli/build.py:284-286`, `effective_force` chama `state_repository.clear()`
antes de `run_pipeline`), então toda combinação com `--force` mostra
"first build" — não é uma falha do T69. Verificado separadamente contra
`tests/fixtures/large_bundle.html` (DB descartável em `/tmp`, fora do
protótipo de referência): duas builds sequenciais **sem** `--force`, a
segunda com um componente extra injetado, produziu `comps_added:
["ExtraDiffWidget"]` corretamente tanto no payload bruto de
`reader.get_build_diff()` quanto na renderização Markdown da tool.

`design-graph validate --db /tmp/c31-rebuild.db`: `status=ok errors=0
warnings=0` (14 screens, 177 components, 64 sections, 86 tokens, 412
CONTAINS).

Suíte: `pytest tests/unit/ -q` → 1732 passed (30 novos testes: 5 de
`get_component_full` no reader + 4 na tool, 5 de paginação de
`list_components`, 5 de `get_build_diff` no reader + 4 na tool, 5 de
round-trip de `last_diff` em `pipeline/state.py` + 2 de `build_new_state`).
`pytest tests/integration/ -q` → 155 passed. `pytest
tests/test_architecture_guardrails.py -q` → 22 passed.
