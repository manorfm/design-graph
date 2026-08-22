# Plan C28 — Truncamento como dado, não log

## Objetivo

Fechar P1 de `spec.md` sem regredir C01–C27, mantendo as guardrails de
arquitetura.

## Critério de aceite

```bash
pytest tests/unit/ -q
pytest tests/integration/ -q
pytest tests/test_architecture_guardrails.py -q
design-graph "iPede Manager v21.2.html" --force --db /tmp/c28-rebuild.db
design-graph validate --db /tmp/c28-rebuild.db
```

Rebuild real sempre contra `/tmp` — nunca a DB de produção do repositório.
`tests/integration/` incluída neste change (não nos anteriores) porque este
é o primeiro a tocar `schema.py`.

## Ordem de implementação

```
T56  extraction/component_extractor.py   — independente
T57  core/models.py                      — depende de T56 (campo já existe na dataclass antes de ser populado)
T58  graph/schema.py + graph/writer.py   — depende de T57 (campo precisa existir no ExtractedComponent antes de persistir)
T59  graph/reader.py                     — depende de T58 (não há o que ler antes de existir no schema)
T60  mcp/tools.py                        — depende de T59 (não há o que exibir antes de existir na leitura)
```

Cadeia estritamente sequencial — cada task consome o que a anterior produziu.

## Validação end-to-end

Rebuild real contra `iPede Manager v21.2.html` (DB descartável em `/tmp`),
comparado ao estado pós-C27 (mesmo arquivo, sem as mudanças deste change):

```
Métrica                     | pós-C27 (baseline) | pós-C28 (final)
-------------------------------|---------------------|------------------
screens / components / tokens  | 14 / 177 / 86       | 14 / 177 / 86 (inalterado)
sections / contains            | 64 / 412            | 64 / 412 (inalterado)
write_errors                   | 0                   | 0
componentes com truncated_fields| n/a (campo não existia)| 36 de 177 (medido)
```

Leitura: nenhuma métrica de extração mudou (campo é aditivo, não altera o
que já era extraído) — mas 36 componentes que hoje se apresentavam como
"spec completa" via MCP passam a carregar um aviso explícito. Verificado
diretamente contra o rebuild real:

```
$ get_component_spec('BasicTab')
# Spec: BasicTab
**Tipo**: tab | **Ocorrências**: 1
**Telas**: ItemEditorV6
> ⚠ Extração truncada em: styles, texts — esta spec pode estar incompleta.
  Chame get_full_jsx('BasicTab') para o JSX bruto.
```

`design-graph validate --db /tmp/c28-rebuild.db`: `status=ok errors=0
warnings=0` (14 screens, 177 components, 64 sections, 86 tokens, 412
CONTAINS).

Suíte: `pytest tests/unit/ -q` → 1683 passed (22 novos testes: 5 de
truncated_fields na extração/consolidate, 2 de persistência no writer, 4 de
round-trip no reader, 11 de helper/wiring nas tools MCP). `pytest
tests/integration/ -q` → 155 passed (sem regressão do schema v7). `pytest
tests/test_architecture_guardrails.py -q` → 22 passed.
