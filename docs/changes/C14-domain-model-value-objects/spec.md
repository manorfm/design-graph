# Spec C14 — Domain model: value objects, enums, entidades ricas

## Problema

`core/models.py` e os módulos que o alimentam tinham "primitive obsession"
real:

- Atributos de conjunto fechado (`StyleEntry.state`, `InteractionEntry.trigger`,
  `TextEntry.text_type`, `DesignToken.category`, `RawSources.format`,
  `ExtractedSection.detection_method`, `ExtractedComponent.comp_type`,
  `DOMPattern.semantic_type`, `ChunkEnvelope.level`) eram `str` cru, sem
  garantia de exaustividade.
- Geração de IDs determinísticos (`prefix + md5(seed)[:8]`) estava duplicada
  em **9 lugares independentes** — 2 cópias idênticas de `_hid`, uma variante
  `_token_id`, e 6 reimplementações inline, incluindo 2 dentro de
  `graph/writer.py` que contornavam o model layer por completo.
- `ComponentProp.default_value == ""` (== obrigatório) era checado com
  lógica duplicada 3× em `mcp/tools.py`, com dois testes (`== ""` e
  truthiness) que só coincidiam por convenção.

Um levantamento (agente Explore, blast radius completo) achou bugs reais de
*drift* causados exatamente por essa falta de tipo: `cli/query.py` sem
`css_var` nos `choices`; schema MCP `get_tokens` listando só 2 de 6
categorias; descrição de `comp_type` sem `table`; duas tuplas
`("default","hover","focus","transition")` duplicadas — `"transition"`
nunca era produzida por nenhum código (membro morto).

## Solução

### `EntityId` — value object

`class EntityId(str)` com `.derive(prefix, seed)` (`prefix_md5(seed)[:8]`) e
`.literal(prefix, suffix)`. Substituiu as 9 duplicações. `derive` recebe o
seed **já montado** pelo chamador (não `*parts`) — preserva byte-a-byte o
formato de cada origem (a maioria junta partes com `_`, uma usa `:`).

### Entidades ricas

`StyleEntry`, `TextEntry`, `InteractionEntry`, `ComponentProp`,
`ExtractedSection` ganharam `classmethod`s nomeados por origem
(`.create()`, `.from_css_class()`, `.for_section()`,
`.from_focus_mutation()`, `.create_semantic()`) que derivam sua própria
identidade — elimina o padrão "calcula o id em algum lugar, passa pro
construtor" espalhado pelos extratores.

`DesignToken` ficou **sem** factory de propósito: `token_extractor.py` tem
7 formas de gerar id (5 hasheadas, 2 literais a partir do valor numérico)
sem fórmula canônica única — cada extrator chama `EntityId.derive`/`.literal`
diretamente.

### Enums

`StyleState`, `InteractionTrigger`, `TextType`, `TokenCategory`,
`SourceFormat`, `DetectionMethod`, `ComponentType`, `SemanticType`,
`ChunkLevel` — todos `class X(_StrEnum)`, onde `_StrEnum(str, Enum)` tem
`__str__` sobrescrito. **Achado durante a implementação**: `(str, Enum)`
sozinho não corrige `str()`/f-string — `Enum.__str__` tem precedência e
produzia `"StyleState.HOVER"` em vez de `"hover"`, o que quebraria qualquer
seed de id construído via f-string (e qualquer log/serialização que chamasse
`str()` no membro). `_StrEnum` corrige isso uma vez para todos os 9 enums.

Membros mortos removidos: `StyleState` sem `TRANSITION`,
`DetectionMethod` sem `NONE`.

### `PropDefault`

`class PropDefault(str)` com `.is_required`. Elimina os 3 blocos duplicados
em `mcp/tools.py`.

### Bônus

`graph/diff.py::compute_screen_hash()` e
`pipeline/state.py::_screen_fingerprint()` eram a mesma lógica duplicada em
2 arquivos — consolidado em `graph/diff.py` (dono natural: já é importado
por `pipeline/coordinator.py`, confirmando a direção de dependência
pipeline→graph já estabelecida no código).

## Invariantes

- **Byte-compatibilidade**: todo id gerado por `EntityId.derive`/`.literal`
  é idêntico ao formato antigo — verificado por teste específico contra o
  algoritmo legado (`prefix + hashlib.md5(seed).hexdigest()[:8]`) e por
  rebuild real do prototype de referência (stats idênticos ao baseline
  pré-refactor).
- `(str, Enum)`/`(str)` em toda parte — leitura (Cypher params, JSON, dict
  keys) não muda em nenhum dos ~60 pontos de consumo identificados; só
  construção ganha tipo.
- Nenhuma mudança de comportamento observável — este é um refactor puro.

## Fora de escopo

- `graph/reader.py` continua devolvendo dicts crus de linha Cypher
  (`.get("t.category", "unknown")`) para `mcp/tools.py`/`cli/report.py` —
  tipar isso é uma mudança arquitetural maior, não uma limpeza pontual.
- `cli/report.py::TokenTableRow.category`/`ComponentSummary.comp_type`
  ficaram `str` deliberadamente — leem de dado persistido (fronteira
  externa, potencialmente de schema antigo); forçar o enum ali faria uma
  única categoria malformada derrubar a tabela de tokens inteira do
  relatório (a função inteira está sob um `try/except` que retorna `[]`).

## Arquivos afetados

| Arquivo | Mudança |
|---|---|
| `src/design_graph/core/models.py` | `EntityId`, `_StrEnum` + 9 enums, `PropDefault`, factories `.create()`/`.for_section()`/etc. |
| `src/design_graph/extraction/component_extractor.py` | remove `_hid`, usa factories, tipa `_COMPONENT_TYPE_MAP` |
| `src/design_graph/extraction/section_extractor.py` | remove `_hid`/`_build_section` local, usa `ExtractedSection.create()` |
| `src/design_graph/extraction/prop_extractor.py` | usa `ComponentProp.create()` |
| `src/design_graph/extraction/plain_html_component_extractor.py` | usa `StyleEntry.create()`, tipa `_SEMANTIC_TYPE_TO_COMP_TYPE` |
| `src/design_graph/parsing/token_extractor.py` | usa `EntityId.derive`/`.literal` diretamente |
| `src/design_graph/parsing/css_class_resolver.py` | usa `StyleEntry.from_css_class()` |
| `src/design_graph/parsing/html_parser.py` | `_infer_semantic_type` retorna `SemanticType` |
| `src/design_graph/parsing/format_detector.py` | constantes viram `SourceFormat` |
| `src/design_graph/graph/writer.py` | `_write_section_styles`/`_write_section_texts` usam os factories `.for_section()` |
| `src/design_graph/mcp/tools.py` | corrige 4 pontos de drift + 3 blocos duplicados de `PropDefault` |
| `src/design_graph/cli/query.py` | `choices=` deriva de `TokenCategory` |
| `src/design_graph/graph/diff.py`, `src/design_graph/pipeline/state.py` | dedup do fingerprint |
| `tests/unit/core/test_models.py` (novo) | `EntityId`, enums, `PropDefault`, factories |
