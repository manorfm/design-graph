# Plan C29 — Estados hover/focus completos

## Objetivo

Fechar P1–P2 de `spec.md` sem regredir C01–C28, mantendo as guardrails de
arquitetura.

## Critério de aceite

```bash
pytest tests/unit/ -q
pytest tests/integration/ -q
pytest tests/test_architecture_guardrails.py -q
design-graph "iPede Manager v21.2.html" --force --db /tmp/c29-rebuild.db
design-graph validate --db /tmp/c29-rebuild.db
```

Rebuild real sempre contra `/tmp` — nunca a DB de produção do repositório.

## Ordem de implementação

```
T61  parsing/css_class_resolver.py + core/models.py   (P1) — independente
T62  extraction/component_extractor.py                (P2) — independente
```

Sem dependência entre as duas — podem rodar em paralelo.

## Validação end-to-end

Rebuild real contra `iPede Manager v21.2.html` (DB descartável em `/tmp`),
comparado ao estado pós-C28 (mesmo arquivo, sem as mudanças deste change):

```
Métrica                     | pós-C28 (baseline) | pós-C29 (final)
-------------------------------|---------------------|------------------
screens / components / tokens  | 14 / 177 / 86       | 14 / 177 / 86 (inalterado)
sections / contains            | 64 / 412            | 64 / 412 (inalterado)
styles / interactions          | 4131 / 30           | 4131 / 30 (inalterado)
write_errors                   | 0                   | 0
```

**Leitura importante**: nenhuma métrica mudou no rebuild real — verificado
que isso é esperado, não uma falha do fix: `grep -o 'hover:[a-zA-Z0-9_-]*'
"iPede Manager v21.2.html" | wc -l` → 1 ocorrência total (não é sequer um
`className` real). Este protótipo usa mutação de estilo via JS
(`onMouseEnter`/`onMouseLeave`, já capturado por C12/C13) para hover, não
classes utilitárias Tailwind com prefixo de estado — não há dado real neste
protótipo específico para o T61 recuperar. A cobertura real de T61 vem dos
6 testes sintéticos (`TestResolveClassesStateVariants`), que reproduzem o
padrão `hover:bg-blue-700` diretamente. T62 (pareamento por propriedade) é
puramente uma correção de bug — sem alteração de contagem esperada mesmo
com dado real, só de qual `from_val` cada interação carrega; confirmado
pelos 2 testes sintéticos (`TestHoverEnterLeavePairingByProperty`) que
reproduzem exatamente o cenário de ordem invertida e comprimento
divergente.

`design-graph validate --db /tmp/c29-rebuild.db`: `status=ok errors=0
warnings=0` (14 screens, 177 components, 64 sections, 86 tokens, 412
CONTAINS).

Suíte: `pytest tests/unit/ -q` → 1693 passed (10 novos testes: 6 de
variantes de estado Tailwind, 2 de seed hover em `from_css_class`, 2 de
pareamento por propriedade). `pytest tests/integration/ -q` → 155 passed.
`pytest tests/test_architecture_guardrails.py -q` → 22 passed.
