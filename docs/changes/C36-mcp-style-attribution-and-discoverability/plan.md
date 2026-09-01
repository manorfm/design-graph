# Plan C36

## Critério de aceite

```bash
pytest tests/unit -q
pytest tests/integration -q
pytest tests/test_architecture_guardrails.py -q
design-graph "toToggle v2.3.html" --force --db /tmp/c36-rebuild-totoggle.db
design-graph validate --db /tmp/c36-rebuild-totoggle.db
```

## Ordem de implementação (TDD red/green/refactor a cada etapa)

```
T80  parsing/js_parser.py                              — P4, independente
T81  core/models.py + extraction/section_extractor.py +
     graph/writer.py + graph/reader.py + mcp/tools.py   — P1 (fundação)
T82  mcp/tools.py                                       — P2, depende de T81
T83  graph/reader.py + mcp/tools.py                     — P5, depende de T81
T84  graph/reader.py + mcp/search.py + mcp/tools.py     — P3, depende de T81
```

## T80 — P4: múltiplos `return` no corpo da função

`extract_return_block` ganha um parâmetro opcional `body_start`. Quando
fornecido e `js[body_start] == "{"` (função com corpo em bloco), todo
`return` que está exatamente um nível de chave dentro do corpo da própria
função é extraído — não só o primeiro. Duas ou mais ocorrências são
concatenadas com marcador `{[return_branch:N]}` (`{[return_branch:default]}`
no último, tratado como o branch principal). Sem `body_start` (todo
chamador/teste existente), comportamento idêntico ao atual — mudança
aditiva, sem regressão. Os dois call sites de produção
(`component_extractor.py`, `screen_extractor.py`) passam a enviar
`boundary.body_start`.

## T81 — P1: atribuição de estilo por seletor + edge perdida

- `core/models.py`: `ExtractedSection` ganha `element_styles: list[StyleEntry]
  = field(default_factory=list)` — aditivo, todo construtor existente
  (produção e teste) continua válido sem alteração.
- `extraction/section_extractor.py`: `_resolve_section_class_styles` (renomeada
  `_resolve_section_element_styles`) devolve `list[StyleEntry]` direto de
  `resolve_classes`, sem colapsar em dict. `_build_section` passa isso para
  o novo campo; `styles` (dict) continua só com os literais `style={{}}`,
  sem o merge de classes que causava a colisão. `_qualifies()` passa a somar
  `len(section.styles) + len(section.element_styles)`.
- `graph/writer.py`: novo método privado único `_write_style_node_once`
  (só a criação do nó, idempotente) usado tanto por `write_component` quanto
  por `_write_section_styles` — a EDGE (`HAS_STYLE`/`SECTION_HAS_STYLE`) é
  sempre criada pelo chamador, nunca pulada por `continue`. Corrige a edge
  perdida para QUALQUER classe compartilhada, não só para seções.
  `_write_section_styles` passa a receber `element_styles: list[StyleEntry]`
  além do dict literal.
- `graph/reader.py`: `get_section_styles` seleciona `s.element`; novo helper
  módulo `_group_section_styles(section_id, rows)` agrupa por seletor
  (`class:X` → rótulo `.X`; `element == section_id` → "estilo próprio da
  seção"). `get_section`/`get_screen_full`/`_assemble_screen_full` usam o
  agrupamento (chave nova `styles_by_element`, substitui `styles` flat).
- `mcp/tools.py`: `get_section`/`get_screen_full` renderizam por grupo,
  mesmo padrão visual de `get_component_spec` (agrupado por estado).

## T82 — P2: `get_full_styles`

Nova tool MCP. Sem query nova no reader — os dados já vêm completos do
reader (`get_section`/`get_component_spec`); o corte de hoje é só a fatia
`[:12]`/`[:6]` na apresentação. `get_full_styles` chama os mesmos métodos
do reader e renderiza toda a lista, sem fatiar. `_truncation_notice` ganha
`recoverable_via` opcional (mesmo padrão já usado por `_truncated_fields_notice`
e `CappedJsx.notice`) para apontar `get_full_styles(...)` nos call sites de
estilo.

## T83 — P5: `get_screen_layout` cobre seções

Depende de T81 (estilos de seção agora têm seletor). `get_screen_layout`
passa a incluir um perfil de layout por (seção, seletor) além de por
componente, reusando `_build_layout_profile` já existente.

## T84 — P3: descoberta de classe CSS compartilhada

- `graph/reader.py`: `find_styles_by_class(class_name)` — busca `Style`
  por `element = 'class:' + name`, mais busca reversa de quem usa (Component
  via `HAS_STYLE`, Section+Screen via `SECTION_HAS_STYLE`+`HAS_SECTION`).
- `mcp/tools.py`: `get_component_spec` cai para `find_styles_by_class` só
  quando a resolução normal de componente não encontra nada — nunca compete
  com um match de componente real. Resposta claramente rotulada como classe
  CSS, não componente React.
- `mcp/search.py`: nova fonte de resultado (`type="CssClass"`) via
  `reader.list_shared_style_classes()`.

## Achado lateral (fora do escopo original, corrigido por ser trivial e no mesmo código)

Ao implementar T84, duas queries novas (`find_styles_by_class`,
`find_class_owners`) falhavam com `Binder exception: Variable X is not in
scope` no Kuzu — causa: `RETURN DISTINCT campo AS alias ... ORDER BY
campo` (referenciando a variável original, não o alias) perde a variável de
escopo depois do `DISTINCT`. Corrigido usando o alias em `ORDER BY` nas
duas queries novas. Não é um bug pré-existente — confirmado que nenhuma
query já existente no reader combina `DISTINCT` com `ORDER BY` na forma
não-aliasada.

## Validação end-to-end — executada em 2026-08-31

T80–T84 implementados em sequência, com o teste RED de cada task escrito
antes da implementação. Suíte completa e guardrails passando após cada
task (1846 → 1853 → 1860 → 1865 testes ao longo da sequência; 2045 no
total unit+integration+guardrails ao final).

```
pytest tests/unit -q                          → 1865 passed
pytest tests/unit tests/integration \
       tests/test_architecture_guardrails.py -q → 2045 passed
design-graph "toToggle v2.3.html" --force --db /tmp/c36-check-totoggle.db
design-graph validate --db /tmp/c36-check-totoggle.db   → status=ok errors=0 warnings=0
design-graph "iPede Manager v21.2.html" --force --db /tmp/c36-check-ipede.db
design-graph validate --db /tmp/c36-check-ipede.db      → status=ok errors=0 warnings=0
```

Verificado manualmente contra o `toToggle` real, exatamente o caso mínimo
do relato original:

- `get_section(screen="HistoryView", section="Audit item")` — estilos agora
  agrupados por seletor (`.audit-item`, `.audit-rail`, `.audit-dot`, ...),
  cada um com seus próprios valores reais (`font-size: 9px`, `width: 18px`
  em `.audit-av`, antes indistinguíveis das outras classes).
- `get_full_styles(screen="HistoryView", section="Audit item")` — lista
  completa sem "+N mais", mesmos grupos.
- `get_screen_layout("HistoryView")` — antes só `# Layout: HistoryView\n##
  Icon`; agora inclui um perfil por seletor da seção "Audit item".
- `get_component_spec("page-title")` — antes "não encontrado"; agora
  devolve `font-size: 25px`, `font-weight: 600`, etc., rotulado como classe
  CSS, com "Usado em: AppList".
- `search("page-title")` — antes zero resultados; agora um resultado
  `CssClass`.
- `get_full_jsx("App")` — antes uma linha (`<FirstLoginScreen .../>`);
  agora os 3 branches (`FirstLoginScreen`, `LoginScreen`, o layout default
  completo com sidebar/`.nav-item`/`.brand`), rotulados
  `{[return_branch:1/2/default]}`.

`get_component_spec("audit-dot")` continua "não encontrado" — causa raiz
diferente (className resolvido dinamicamente, ver spec.md "Fora de
escopo"), não coberta por este change.
