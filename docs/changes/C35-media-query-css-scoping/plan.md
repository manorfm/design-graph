# Plan C35 — `@media` corrompe a resolução de classe CSS

## Objetivo

Fechar P1 (obrigatório) e P2 (feature) de `spec.md` sem regredir C01–C34,
mantendo as guardrails de arquitetura. Ambos implementados nesta rodada —
T77 primeiro (isolado, testado e verificado sozinho), T78 depois, sobre a
base já corrigida por T77.

## Critério de aceite

```bash
pytest tests/unit/ -q
pytest tests/integration/ -q
pytest tests/test_architecture_guardrails.py -q
design-graph "iPede Manager v21.2.html" --force --db /tmp/c35-rebuild-ipede.db
design-graph "toToggle v2.2.html" --force --db /tmp/c35-rebuild-totoggle.db
design-graph validate --db /tmp/c35-rebuild-ipede.db
design-graph validate --db /tmp/c35-rebuild-totoggle.db
```

Rebuild real sempre contra `/tmp` — nunca a DB de produção do repositório.

## Ordem de implementação

```
T77  parsing/css_class_resolver.py                                     — obrigatório, independente
T78  parsing/css_class_resolver.py + core/models.py + graph/schema.py +
     graph/writer.py + graph/reader.py + extraction/component_extractor.py +
     pipeline/coordinator.py + mcp/tools.py                            — depende de T77
```

## Validação end-to-end — executada em 2026-08-30

T77 e T78 implementados. Suíte completa e guardrails passando após cada um:

```
# Após T77
pytest tests/unit/ -q                          → 1797 passed
pytest tests/integration/ -q                   →  155 passed
pytest tests/test_architecture_guardrails.py -q →  22 passed

# Após T78 (inclui os 11 testes novos de T78)
pytest tests/unit/ -q                          → 1808 passed
pytest tests/integration/ -q                   →  155 passed
pytest tests/test_architecture_guardrails.py -q →  22 passed
```

Testes novos em `tests/unit/parsing/test_css_class_resolver.py`
(`TestStripMediaBlocks`, `TestExtractCssRulesIgnoresMedia`,
`TestExtractTagPseudoRulesIgnoresMedia`) cobrem: `@media` simples e
composto (`and`), condição não-dimensional (`hover:none`), múltiplos
blocos, chaves aninhadas dentro do bloco, e o caso `.page-title` como
regressão direta.

Rebuild real contra `toToggle v2.2.html` (`/tmp/c35-rebuild-totoggle.db`),
consultando o grafo reconstruído diretamente (não só a função isolada) para
o componente `AppList` (`classes` inclui `page-title`):

```
                          | pré-C35 (bug, confirmado na investigação) | pós-T77 (grafo real, verificado)
--------------------------|--------------------------------------------|-----------------------------------
.page-title → font-size   | 21px (valor mobile, sem indicação)         | 25px (valor default real)
.page-title → font-weight | (ausente)                                  | 600
.page-title → letter-sp.  | (ausente)                                  | -0.025em
```

Query usada (`GraphReader._q` contra a DB reconstruída):

```cypher
MATCH (c:Component {name:'AppList'})-[:HAS_STYLE]->(s:Style)
WHERE s.element = 'class:page-title'
RETURN s.property, s.value, s.state
```

Stats gerais do rebuild de `toToggle v2.2.html` só com T77: 8 screens, 53
components (52 extraídos + 1 unresolved), 82 tokens, 4 sections, 835
styles, 115 CONTAINS — primeiro rebuild registrado deste protótipo; passa
a ser fixture de referência para `@media`, junto de `iPede Manager
v21.2.html` para o resto do pipeline.

### T78 — validação end-to-end via `get_component_spec` real

Rebuild com T78 aplicado (`/tmp/c35-t78-totoggle.db`): **835 → 869 Styles**
(+34) — exatamente as novas entradas `media`-scoped, nenhuma remoção
(T77 não regrediu). Componente/schema/writer/reader/tool exercitados
ponta a ponta via `ToolDispatcher.get_component_spec(reader, "AppList")`
contra a DB reconstruída:

```markdown
## Estilos — default
| font-size | 25px | 14px | 13.5px |
...

## Estilos responsivos
Valores abaixo só se aplicam sob a condição `@media` indicada — não
confundir com o valor default acima.

**`@media (max-width:1024px)`**
| flex-wrap | wrap | padding-left | 20px | padding-right | 20px |

**`@media (max-width:600px)`**
| font-size | 21px | 13px | gap | 12px | margin-bottom | 20px | ...

**`@media (min-width:1600px)`**
| max-width | 1240px |

**`@media (max-width:1180px)`**
| max-width | none |
```

Confirma: (1) `## Estilos — default` não contém mais `21px` misturado —
P1 continua corrigido; (2) as quatro condições `@media` do componente
aparecem separadas, com seus próprios valores, nunca fundidas entre si
nem com o default — P2 entregue sem reabrir P1.

Regressão em `iPede Manager v21.2.html` (`/tmp/c35-t78-ipede.db`, sem
`@media`): stats idênticos ao baseline pós-T77/pós-C34 (comps=182,
unresolved=6, tokens=86, sections=64, contains=419, styles=4131) — T78
também é no-op nesse protótipo, como esperado.

## Regressão

Rebuild comparativo contra `iPede Manager v21.2.html`
(`/tmp/c35-rebuild-ipede.db`), protótipo de referência de C01–C34 sem
`@media` conhecido:

```
Métrica            | pós-C34 (baseline) | pós-C35/T77
---------------------|---------------------|---------------
components           | 182                 | 182 (inalterado)
unresolved_components| 6                   | 6 (inalterado)
contains_rels         | 419                 | 419 (inalterado)
tokens                | 86                  | 86 (inalterado)
sections               | 64                  | 64 (inalterado)
```

Stats idênticos ao baseline — confirma que T77/T78 só alteram comportamento
quando `@media` está presente no CSS de entrada, exatamente como esperado
(`iPede Manager v21.2.html` não usa `@media`).
