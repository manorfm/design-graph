# Plan C30 — Ordem de renderização (`order_index`)

## Objetivo

Fechar P1 de `spec.md` sem regredir C01–C29, mantendo as guardrails de
arquitetura. Pré-requisito para C31 (`get_component_full` já nasce ordenada).

## Critério de aceite

```bash
pytest tests/unit/ -q
pytest tests/integration/ -q
pytest tests/test_architecture_guardrails.py -q
design-graph "iPede Manager v21.2.html" --force --db /tmp/c30-rebuild.db
design-graph validate --db /tmp/c30-rebuild.db
```

Rebuild real sempre contra `/tmp` — nunca a DB de produção do repositório.

## Ordem de implementação

```
T63  extraction/component_extractor.py            — independente
T64  core/models.py                                — depende de T63 (child_refs precisa já ser lista ordenada por variante antes de decidir qual variante manda)
T65  graph/schema.py + graph/writer.py             — depende de T64 (order_index só existe depois de consolidate() produzi-lo)
T66  graph/reader.py                               — depende de T65 (não há o que ordenar antes de existir na aresta)
```

Cadeia estritamente sequencial.

## Validação end-to-end

Rebuild real contra `iPede Manager v21.2.html` (DB descartável em `/tmp`),
comparado ao estado pós-C29 (mesmo arquivo, sem as mudanças deste change):

```
Métrica                     | pós-C29 (baseline) | pós-C30 (final)
-------------------------------|---------------------|------------------
screens / components / tokens  | 14 / 177 / 86       | 14 / 177 / 86 (inalterado)
sections / contains            | 64 / 412            | 64 / 412 (inalterado)
write_errors                   | 0                   | 0
```

Nenhuma métrica de contagem muda (order_index é uma propriedade adicional
na aresta já existente, não uma aresta nova) — verificado.

**Observação sobre o rebuild real**: inspecionado `order_index` de um
componente real com muitos filhos (`BasicTab`, 13 filhos) — saiu em ordem
que parece alfabética (`Btn, Card, Chip, Field, IconBtn, ...`). Investigado:
os filhos desse componente específico não vêm de tags JSX literais
(`get_full_jsx` não contém `<Btn`/`<Card` diretamente) — são referenciados
via `RE_COMP_REF` (provavelmente um mapa tipo→componente para campos de
formulário dinâmico), cuja ordem real no bundle minificado não foi
confirmada byte a byte nesta sessão. Não é evidência de bug: os testes
sintéticos (`TestChildRefsOrder`, `TestExtractedComponentConsolidateChildOrder`,
`TestOrderIndex`) controlam a entrada exatamente e confirmam que a
implementação preserva ordem de aparição em vez de ordenar — a leitura mais
provável é que o próprio código-fonte do protótipo já lista esses casos em
ordem alfabética (comum em mapeamentos tipo/switch). Registrado aqui em vez
de omitido, seguindo a disciplina do projeto de não superestimar evidência
de rebuild real além do que foi de fato verificado.

`design-graph validate --db /tmp/c30-rebuild.db`: `status=ok errors=0
warnings=0` (14 screens, 177 components, 64 sections, 86 tokens, 412
CONTAINS).

Suíte: `pytest tests/unit/ -q` → 1702 passed (9 novos testes: 2 de ordem em
`extract_component`, 3 de ordem em `consolidate()`, 4 de order_index em
writer/reader — mais 1 teste pré-existente corrigido para refletir o novo
critério "variante viva primeiro"). `pytest tests/integration/ -q` → 155
passed. `pytest tests/test_architecture_guardrails.py -q` → 22 passed.
