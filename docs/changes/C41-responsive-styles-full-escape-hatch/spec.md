# Spec C41 — `get_full_styles` passa a cobrir estilos responsivos (`@media`)

## Contexto

Item levantado numa auditoria de status pós-C38/C39: `get_component_spec`
é a única tool que expõe estilos `@media`-scoped ("Estilos responsivos"),
mas trunca cada condição em 12 linhas sem apontar como recuperar o resto —
`get_full_styles` (o escape hatch de estilo desde C36) deliberadamente não
cobria esse caso.

## Problemas

### P1 — Sem escape hatch para estilos responsivos

`get_component_spec`'s notice de corte pra "Estilos responsivos" não
passava `recoverable_via` — nem para `get_full_styles`, que de qualquer
forma não teria o dado (só renderizava `styles_by_state`, nunca
`responsive_styles_by_media`, embora `reader.get_component_spec` já
devolvesse os dois sem corte).

### P2 — Achado colateral: componente só com estilo responsivo dava falso "sem estilo"

`get_full_styles(name=X)` checava só `spec.get("styles_by_state")` antes
de decidir "Nenhum estilo encontrado" — um componente com estilo default
zero mas `@media` real (caso plausível: todo o estilo do componente muda
só abaixo de um breakpoint) reportava incorretamente que não tinha estilo
nenhum.

## Solução

- `mcp/tools.py`: `get_component_spec` passa `recoverable_via=cname` na
  notícia de corte de "Estilos responsivos" (antes sem ponteiro).
- `get_full_styles(name=X)` passa a checar `styles_by_state` **ou**
  `responsive_styles_by_media` antes de reportar "sem estilo", e renderiza
  uma seção "## Estilos responsivos" completa (sem corte), agrupada por
  condição `@media`, mesma separação de P1/C35 que `get_component_spec`
  já aplica (nunca misturado no valor default).

## Verificação

```
pytest tests/unit -q                              → 1941 passed
pytest tests/unit tests/integration \
       tests/test_architecture_guardrails.py -q   → 2122 passed
```

Confirmado contra o `toToggle v2.6` real: `get_full_styles("WelcomeStep")`
mostra as duas condições `@media (max-width:1024px)` e
`@media (max-width:600px)` completas (antes, nenhuma aparecia).
