# Plan C35 — `@media` corrompe a resolução de classe CSS

## Objetivo

Fechar P1 de `spec.md` (obrigatório) sem regredir C01–C34, mantendo as
guardrails de arquitetura. P2 é proposto no mesmo change; decisão de
incluir ou adiar para um C36 fica a critério de quem revisar o spec — T77
sozinho já corrige o bug de corrupção e deixa o comportamento igual ao que
a docstring de `extract_css_rules` sempre prometeu ("ignora @media").

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
T77  parsing/css_class_resolver.py                              — obrigatório, independente
T78  parsing/css_class_resolver.py + core/models.py + mcp/tools.py — proposto, depende de T77
```

## Validação end-to-end — executada em 2026-08-30

T77 implementado. Suíte completa e guardrails passando:

```
pytest tests/unit/ -q                          → 1797 passed
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

Stats gerais do rebuild de `toToggle v2.2.html`: 8 screens, 53 components (52
extraídos + 1 unresolved), 82 tokens, 4 sections, 835 styles, 115 CONTAINS —
primeiro rebuild registrado deste protótipo; passa a ser fixture de
referência para `@media`, junto de `iPede Manager v21.2.html` para o resto
do pipeline.

**T78 não implementado nesta rodada** — decisão explícita, não pendência
esquecida. Exporia estilos responsivos via `get_component_spec`, mas exige
mudança de schema do grafo (nova coluna `media` na tabela `Style`,
propagação por ~7 queries distintas em `reader.py`, novo parâmetro em
`StyleEntry.from_css_class`, e renderização nova em `mcp/tools.py`) —
superfície proporcionalmente maior e mais arriscada que T77, sem o gate de
revisão de spec que o resto do projeto usa antes de mudança de schema.
Fica proposto para um change futuro (C36 ou T78 revisitado aqui) se o valor
de expor a condição de media query for confirmado como necessário.

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

Stats idênticos ao baseline — confirma que T77 só altera comportamento
quando `@media` está presente no CSS de entrada, exatamente como esperado
(`iPede Manager v21.2.html` não usa `@media`).
