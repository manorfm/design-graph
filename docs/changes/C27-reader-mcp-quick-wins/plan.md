# Plan C27 — Reader/MCP: ganhos rápidos

## Objetivo

Fechar P1–P4 de `spec.md` sem regredir C01–C26, mantendo as guardrails de
arquitetura.

## Critério de aceite

```bash
pytest tests/unit/ -q
pytest tests/test_architecture_guardrails.py -q
design-graph "iPede Manager v21.2.html" --force --db /tmp/c27-rebuild.db
design-graph validate --db /tmp/c27-rebuild.db
```

Rebuild real sempre contra `/tmp` — nunca a DB de produção do repositório.

## Ordem de implementação

```
T52  graph/reader.py                       (P1) — independente
T53  mcp/tools.py + mcp/server.py          (P2) — independente
T54  graph/reader.py + mcp/tools.py        (P3) — independente
T55  mcp/tools.py + README.md              (P4) — independente
```

Os quatro podem rodar em paralelo — nenhuma dependência entre eles.

## Validação end-to-end

Rebuild real contra `iPede Manager v21.2.html` (DB descartável em `/tmp`),
comparado ao estado pós-C26 (mesmo arquivo, sem as mudanças deste change):

```
Métrica                     | pós-C26 (baseline) | pós-C27 (final)
-------------------------------|---------------------|------------------
screens / components / tokens  | 14 / 177 / 86       | 14 / 177 / 86 (inalterado)
sections / contains            | 64 / 412            | 64 / 412 (inalterado)
write_errors                   | 0                   | 0
```

Leitura: C27 é uma mudança de camada de leitura/API — nenhuma métrica de
extração deveria mudar, e nenhuma mudou. `design-graph validate --db
/tmp/c27-rebuild.db`: `status=ok errors=0 warnings=0`.

Suíte: `pytest tests/unit/ -q` → 1661 passed (10 novos testes: 3 de fast-path
fuzzy, 2 de validação de nome malformado, 2 de mensagem
não-encontrado/folha, 2 de `component_exists`, 1 de reader `_q` spy).
`pytest tests/test_architecture_guardrails.py -q` → 22 passed.
