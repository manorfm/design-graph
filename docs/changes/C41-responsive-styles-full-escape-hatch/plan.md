# Plan C41

## T96 — `mcp/tools.py`

- `get_component_spec`: `_truncation_notice(len(styles), 12, recoverable_via=cname)`
  na seção "Estilos responsivos" (antes sem `recoverable_via`).
- `get_full_styles`: guarda de "sem estilo" passa a checar
  `styles_by_state or responsive_styles_by_media`; nova seção "## Estilos
  responsivos" (sem corte) depois da seção por estado, mesmo agrupamento
  por condição `@media` de `get_component_spec`.

Testes novos em `tests/unit/mcp/test_tools.py`: `TestGetFullStylesTool`
(componente só com estilo responsivo não reporta "sem estilo"; lista sem
corte; default e responsivo não se misturam) e
`TestTruncationNoticesPointToFullTools` (notice de estilo responsivo
aponta pra `get_full_styles`).
