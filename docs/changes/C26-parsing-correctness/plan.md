# Plan C26 — Correções de bugs de parsing

## Objetivo

Fechar P1–P3 de `spec.md` sem regredir C01–C25, mantendo as guardrails de
arquitetura.

## Critério de aceite

```bash
pytest tests/unit/ -q
pytest tests/test_architecture_guardrails.py -q
design-graph "iPede Manager v21.2.html" --force --db /tmp/c26-rebuild.db
design-graph validate --db /tmp/c26-rebuild.db
```

Rebuild real sempre contra `/tmp` — nunca a DB de produção do repositório.

## Ordem de implementação

```
T49  parsing/html_parser.py               (P1) — independente
T50  extraction/section_extractor.py      (P2) — independente
T51  extraction/component_extractor.py    (P3) — independente
```

Os três podem rodar em paralelo — nenhuma dependência entre eles.

## Validação end-to-end

Rebuild real contra `iPede Manager v21.2.html` (DB descartável em `/tmp`),
comparado ao estado pós-C25 (mesmo arquivo, sem as mudanças deste change):

```
Métrica                     | pós-C25 (baseline) | pós-C26 (final)
-------------------------------|---------------------|------------------
screens / components / tokens  | 14 / 177 / 86       | 14 / 177 / 86 (inalterado)
sections                       | 64                  | 64 (inalterado)
contains                       | 412                 | 412 (inalterado)
styles / texts / interactions  | 4131 / 1796 / 30    | 4131 / 1796 / 30 (inalterado)
write_errors                   | 0                   | 0
```

Leitura: nenhuma métrica caiu (critério de aceite do spec — "não pode cair"),
confirmando que as três correções não regrediram a extração no protótipo de
referência. Os três bugs corrigidos (except genérico, div não-balanceado,
spread ambíguo) não têm evidência de disparo neste protótipo específico —
por isso a validação real aqui é "sem regressão" + testes unitários
sintéticos que reproduzem cada bug isoladamente (ver spec.md).

`design-graph validate --db /tmp/c26-rebuild.db`: `status=ok errors=0
warnings=0` (14 screens, 177 components, 64 sections, 86 tokens, 412
CONTAINS).

Suíte: `pytest tests/unit/ -q` → 1652 passed (4 novos testes: 3 de
`_find_balanced_div_end`/`_detect_by_structure`, 1 de resolução de spread
ambíguo). `pytest tests/test_architecture_guardrails.py -q` → 22 passed.
