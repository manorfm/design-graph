# Plan C39

## Critério de aceite

```bash
pytest tests/unit -q
pytest tests/integration -q
pytest tests/test_architecture_guardrails.py -q
design-graph "toToggle v2.6.html" --force
design-graph validate --db "~/.local/share/design-graph/toToggle v2.6.db"
```

## Ordem de implementação

```
T88  parsing/js_parser.py                                — find_module_level_constants (base compartilhada)
T89  extraction/module_text_extractor.py                 — P2, depende de T88
T90  extraction/module_data_extractor.py (novo)           — P1, depende de T88
T91  core/models.py + extraction/component_extractor.py
     + pipeline/coordinator.py                            — P1, depende de T90
T92  graph/schema.py + graph/writer.py + graph/reader.py  — P1, depende de T91
T93  mcp/tools.py + mcp/server.py                          — P1, depende de T92
T94  core/models.py + pipeline/state.py + pipeline/coordinator.py
     + graph/reader.py + mcp/tools.py                      — P3, independente
```

## T88 — `find_module_level_constants`

`parsing/js_parser.py` ganha `find_module_level_constants(js, boundaries) ->
dict[name, raw_literal]`: mesma regra de C38 (`const NOME = ` seguido de `{`
ou `[`, fora de todo `FunctionBoundary`), generalizada para os dois tipos
de abertura e para ser reutilizada por dois consumidores (T89, T90) em vez
de cada um reimplementar a varredura.

## T89 — P2: objetos em `module_text_extractor.py`

Refatorado para consumir `find_module_level_constants` (em vez do regex
próprio de array). `_extract_copy_pairs(obj_body, constant_name, depth)`
generaliza a extração de `key: "string"` já usada para elementos de array,
reaplicada também ao corpo de um objeto direto — recursão de 1 nível para
o caso `ROLE_META`-shaped (`root: { label: 'Root' }`). Toda a suíte de
testes existente (array) permanece verde sem alteração; testes novos
cobrem objeto plano e aninhado.

## T90 — P1: `module_data_extractor.py`

Novo módulo, função pura `extract_referenced_module_data(component_body,
module_constants) -> dict[str, JsonValue]`. `_literal_to_jsonable`
converte um literal `{...}`/`[...]` recursivamente (até profundidade 2) em
estrutura só-de-string; um valor não-string (identificador, número,
expressão) é descartado, não adivinhado.

## T91 — Fiação em `component_extractor.py`/`coordinator.py`

- `ExtractedComponent.referenced_data: dict[str, object] = {}` (aditivo);
  `consolidate()` faz union por variante (last-wins por chave repetida).
- `extract_component`/`extract_all_components` ganham `module_constants:
  dict[str,str] | None = None` (aditivo, default preserva todo call site
  existente).
- `pipeline/coordinator.py`: `module_constants = find_module_level_constants
  (sources.js, all_boundaries)` computado uma vez, passado a
  `extract_all_components`.

## T92 — Schema + writer + reader

- `graph/schema.py`: `Component.referenced_data_json STRING` (schema v9).
- `graph/writer.py`: `write_component` serializa via `json.dumps`;
  `_ensure_component_exists` (shell UNRESOLVED) grava `''`.
- `graph/reader.py`: `get_component`/`get_component_spec`/
  `get_component_full`/`_assemble_screen_full` deserializam e expõem
  `"referenced_data"` (dict) ao lado dos campos já existentes.

## T93 — MCP

- `mcp/tools.py`: `_referenced_data_lines` (renderização com aviso de
  corte, reaproveitando `_truncation_notice(..., tool="get_component_data")`)
  usado em `get_component`/`get_component_spec`/`get_component_full`/
  `get_screen_full`. Nova tool `get_component_data(name)` — versão sem
  corte, mesmo papel de `get_full_styles`/`get_full_texts`.
- `mcp/server.py`: `_AGENT_INSTRUCTIONS` ganha nota para reusar os valores
  de "Dados referenciados" em vez de inventar um ícone/asset equivalente.

## T94 — P3: `skipped_entries` visível

- `core/models.py`: `BuildState.skipped_entries: int = 0` (aditivo).
- `pipeline/state.py`: persiste/lê o campo; default 0 para state.json
  anterior a este change (sem crash, sem falso-positivo).
- `pipeline/coordinator.py`: `build_new_state(..., skipped_entries=
  sources.skipped_entries)`.
- `graph/reader.py`: `get_build_diff()` inclui `skipped_entries` no dict
  devolvido (antes só devolvia o `last_diff` aninhado).
- `mcp/tools.py`: `get_build_diff` calcula o aviso ANTES dos três `return`
  antecipados (primeira build / sem mudança / diff normal) — um build pode
  pular entradas em qualquer um desses três casos, e o aviso não pode
  depender de qual mensagem seria mostrada.

## Validação end-to-end — executada em 2026-09-06

```
pytest tests/unit -q                              → 1926 passed
pytest tests/unit tests/integration \
       tests/test_architecture_guardrails.py -q   → 2113 passed
design-graph "toToggle v2.6.html" --force          → screens=10 comps=58 UITexts=492 (antes 440)
design-graph validate --db ".../toToggle v2.6.db"  → status=ok errors=0 warnings=0
```

Verificado manualmente (via `ToolDispatcher` direto contra o banco
reconstruído — a conexão MCP já ativa nesta sessão ainda rodava o código
anterior a este change, então precisa de reconexão para refletir isso ao
vivo):

- `get_component_spec("Icon")` — seção "Dados referenciados" com `ICONS`,
  35 de 39 entradas mostradas + aviso `chame get_component_data(Icon)`.
- `get_component_data("Icon")` — as 39 entradas completas, sem corte,
  path SVG real por nome (`lock`, `trash`, `star`, ...).
- `get_component_spec("RoleBadge")` — `ROLE_META` aninhado com
  `bg`/`color`/`label` reais para `root`/`admin`/`user`.
- `UITexts`: 440 → 492 (52 textos de `ROLE_META` e outros objetos de
  módulo antes invisíveis a `search()`).
- `Unresolved`: confirmado em 0 (achado de C38, continua corrigido).
