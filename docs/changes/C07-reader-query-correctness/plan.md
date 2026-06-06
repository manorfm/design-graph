# Plan C07 — Correção da Query Transitiva

## Objetivo

Corrigir o bug em `find_screens_using_comp_transitively()` que impede a busca
de telas por componente em qualquer nível de composição além do direto.

## Critério de aceite

```bash
pytest tests/unit/graph/test_writer_reader.py::TestFindScreensTransitively -v
# todos os novos testes verdes
```

## Sequência TDD

### RED — escrever testes que falham

Adicionar a `tests/unit/graph/test_writer_reader.py` (ou criar `test_reader_transitive.py`):

```python
class TestFindScreensTransitiveFix:
    """Tests for fixed USES_COMPONENT + CONTAINS traversal."""

    def test_direct_component_found(self, populated_reader):
        # SectionCard está diretamente em RestaurantsPage via USES_COMPONENT
        screens = populated_reader.find_screens_using_comp_transitively("SectionCard")
        assert "RestaurantsPage" in screens

    def test_child_component_found_via_contains(self, populated_reader):
        # BtnPrimary está dentro de SectionCard (CONTAINS depth 1)
        # Deve encontrar RestaurantsPage
        screens = populated_reader.find_screens_using_comp_transitively("BtnPrimary")
        assert "RestaurantsPage" in screens

    def test_grandchild_component_found_via_contains(self, populated_reader):
        # Badge está dentro de BtnPrimary (CONTAINS depth 2)
        # Deve encontrar RestaurantsPage
        screens = populated_reader.find_screens_using_comp_transitively("Badge")
        assert "RestaurantsPage" in screens

    def test_unknown_component_returns_empty(self, populated_reader):
        assert populated_reader.find_screens_using_comp_transitively("NonExistent") == []

    def test_result_is_list_of_strings(self, populated_reader):
        result = populated_reader.find_screens_using_comp_transitively("Badge")
        assert isinstance(result, list)
        assert all(isinstance(s, str) for s in result)
```

O fixture `populated_reader` precisa ter:
- `RestaurantsPage` → `[USES_COMPONENT]` → `SectionCard`
- `SectionCard` → `[CONTAINS]` → `BtnPrimary`
- `BtnPrimary` → `[CONTAINS]` → `Badge`

### GREEN — implementar a correção mínima

Em `src/design_graph/graph/reader.py`, substituir o corpo de `find_screens_using_comp_transitively`:

```python
def find_screens_using_comp_transitively(self, comp_name: str) -> list[str]:
    rows = self._q(
        "MATCH (s:Screen)-[:USES_COMPONENT]->(p:Component)"
        "-[:CONTAINS*0..3]->(c:Component {name:$n}) "
        "RETURN DISTINCT s.name ORDER BY s.name",
        {"n": comp_name},
    )
    logger.debug(
        "reader: find_screens_transitively(%s) → %d screens",
        comp_name, len(rows),
    )
    return [r["s.name"] for r in rows]
```

### BLUE — verificar impacto

`get_impact()` chama `find_screens_using_comp_transitively()` internamente.
Verificar que os testes de `get_impact` continuam passando e que o resultado
é agora mais rico (retorna telas via composição).

## Guardrails a verificar

- G3: `reader.py` não pode conter `CREATE`, `DELETE`, `MERGE`
- G5: `GraphReader` recebe conexão `read_only=True`

## Esforço estimado

Mudança de 1 linha na query + 5 novos testes. ~30 minutos.
