# Spec C07 — Correção da Query Transitiva de Telas

## Problema

`GraphReader.find_screens_using_comp_transitively()` usa a query:

```cypher
MATCH (s:Screen)-[:USES_COMPONENT*1..3]->(c:Component {name:$n})
RETURN DISTINCT s.name
```

Essa query tenta fazer um path variável sobre `USES_COMPONENT`, mas essa relação
existe apenas no sentido `Screen → Component`. Não existe `Component → Component`
via `USES_COMPONENT` — essa hierarquia usa `CONTAINS`. Logo, `*1..3` nunca
encontra resultados além do nível direto (`*1`). A query se comporta identicamente
a `*1..1`, tornando o "transitivo" ineficaz.

### Exemplo de falha

```
RestaurantsPage
  └─[USES_COMPONENT]→ SectionCard
       └─[CONTAINS]→ BtnPrimary
            └─[CONTAINS]→ Badge
```

`find_screens_using_comp_transitively("Badge")` deveria retornar `["RestaurantsPage"]`.
Com a query atual retorna `[]`.

## Solução

Combinar `USES_COMPONENT` (Screen→Component) com `CONTAINS*0..N` (Component→Component):

```cypher
MATCH (s:Screen)-[:USES_COMPONENT]->(p:Component)-[:CONTAINS*0..3]->(c:Component {name:$n})
RETURN DISTINCT s.name ORDER BY s.name
```

`CONTAINS*0..3` cobre:
- `*0` — o próprio componente (componente usado diretamente pela tela)
- `*1..3` — até 3 níveis de composição (filho, neto, bisneto)

## Invariante

O método continua **read-only** (G3 guardrail). Nenhum `CREATE`, `DELETE` ou `MERGE`.
O log de debug deve registrar o componente pesquisado e o número de telas encontradas.

## Contrato após correção

```python
def find_screens_using_comp_transitively(self, comp_name: str) -> list[str]:
    """
    Return screen names that use comp_name directly or via CONTAINS composition
    (up to 3 levels deep). Uses USES_COMPONENT + CONTAINS traversal.
    """
```

## Casos de teste

| Cenário | Entrada | Resultado esperado |
|---|---|---|
| Componente direto numa tela | `SectionCard` | `["RestaurantsPage"]` |
| Componente filho (CONTAINS depth 1) | `BtnPrimary` | `["RestaurantsPage"]` |
| Componente neto (CONTAINS depth 2) | `Badge` | `["RestaurantsPage"]` |
| Componente sem uso em nenhuma tela | `Orphan` | `[]` |
| Nome inexistente | `"NonExistent"` | `[]` |
| Componente em múltiplas telas | `SharedBtn` | todas as telas |

## Arquivos afetados

| Arquivo | Tipo de mudança |
|---|---|
| `src/design_graph/graph/reader.py` | Correção de query — 1 linha |
| `tests/unit/graph/test_writer_reader.py` | Novos testes de composição transitiva |
