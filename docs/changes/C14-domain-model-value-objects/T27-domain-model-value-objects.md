# T27 — Domain model: EntityId, enums, PropDefault, entidades ricas

**Arquivo:** `src/design_graph/core/models.py` (+ todos os produtores de entidade listados na spec)
**Depende de:** T06, T20 (ComponentExtractor, TokenExtractor)
**Status:** ✅ done

## Responsabilidade

Substituir "primitive obsession" por tipos com significado e comportamento:
`EntityId` (identidade determinística), enums `(str, Enum)` para todo
atributo de conjunto fechado, `PropDefault` (semântica de "obrigatório"),
e factories nomeadas por origem em cada entidade com múltiplos produtores.

## Critério de aceite

- `EntityId.derive`/`.literal` produzem exatamente o mesmo formato que os 9
  geradores de id duplicados que substituem (`_hid` ×2, `_token_id`, 6
  reimplementações inline) — testado por comparação direta com o algoritmo
  legado.
- 9 enums (`StyleState`, `InteractionTrigger`, `TextType`, `TokenCategory`,
  `SourceFormat`, `DetectionMethod`, `ComponentType`, `SemanticType`,
  `ChunkLevel`) via `_StrEnum` — sem os 2 membros mortos
  (`StyleState.TRANSITION`, `DetectionMethod.NONE`).
- `PropDefault.is_required` substitui as 3 checagens duplicadas em
  `mcp/tools.py`.
- Factories `.create()`/`.for_section()`/`.from_css_class()`/
  `.from_focus_mutation()`/`.create_semantic()` em `StyleEntry`, `TextEntry`,
  `InteractionEntry`, `ComponentProp`, `ExtractedSection`.
- `graph/writer.py` não constrói mais `Style`/`UIText` de seção via Cypher
  literal manual — usa as factories `.for_section()`.
- 4 pontos de drift corrigidos (`cli/query.py` choices, schema MCP
  `get_tokens`, descrição `comp_type`, 2 tuplas hardcoded de estado).
- Testes novos em `tests/unit/core/test_models.py` (37 testes).
- Suíte completa (`pytest -q`) sem regressão — 1539 testes.
- Rebuild real do prototype de referência com stats idênticos ao baseline
  pré-refactor.
