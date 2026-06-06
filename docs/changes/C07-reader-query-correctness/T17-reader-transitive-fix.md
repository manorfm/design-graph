# T17 — GraphReader: Fix Transitive Screen Query

**Change**: C07 — Reader Query Correctness
**Arquivo**: `src/design_graph/graph/reader.py`
**Depende de**: T11 (GraphReader implementado), T10 (GraphWriter com CONTAINS)
**Bloqueia**: nada (correção isolada)

---

## Contexto

`find_screens_using_comp_transitively()` usa `USES_COMPONENT*1..3` que não tem
efeito prático — USES_COMPONENT existe apenas Screen→Component. A query nunca
atravessa a hierarquia Component→Component (que usa CONTAINS).

Resultado: `impact("Badge")` retorna `screens: []` mesmo quando Badge está
em BtnPrimary que está em SectionCard que está em RestaurantsPage.

---

## Contrato

```python
def find_screens_using_comp_transitively(self, comp_name: str) -> list[str]:
    """
    Return screen names that use comp_name directly or via CONTAINS composition
    up to 3 levels deep.

    Query pattern:
      Screen -[USES_COMPONENT]-> AnyComponent -[CONTAINS*0..3]-> TargetComponent
    """
```

---

## TDD

### Fixture necessária

O fixture `populated_reader` (ou um fixture novo `contains_populated_reader`)
deve ter:

```
RestaurantsPage
  ─[USES_COMPONENT]→ SectionCard
       ─[CONTAINS]→ BtnPrimary
            ─[CONTAINS]→ Badge

LoginPage
  ─[USES_COMPONENT]→ BtnPrimary (diretamente)
```

### Testes (RED primeiro)

```python
class TestFindScreensTransitiveFix:
    def test_direct_usage_found(self, reader):
        # SectionCard está direto na tela
        assert "RestaurantsPage" in reader.find_screens_using_comp_transitively("SectionCard")

    def test_contains_depth_1_found(self, reader):
        # BtnPrimary está em SectionCard (depth 1)
        result = reader.find_screens_using_comp_transitively("BtnPrimary")
        assert "RestaurantsPage" in result
        assert "LoginPage" in result  # também direto

    def test_contains_depth_2_found(self, reader):
        # Badge está em BtnPrimary (depth 2 via SectionCard)
        result = reader.find_screens_using_comp_transitively("Badge")
        assert "RestaurantsPage" in result
        assert "LoginPage" in result  # via BtnPrimary direto

    def test_no_false_positives(self, reader):
        # Componente que não está em nenhuma tela
        assert reader.find_screens_using_comp_transitively("OrphanComp") == []

    def test_result_deduplicado(self, reader):
        # Badge pode ser alcançado por múltiplos caminhos — sem duplicatas
        result = reader.find_screens_using_comp_transitively("Badge")
        assert len(result) == len(set(result))

    def test_returns_sorted(self, reader):
        result = reader.find_screens_using_comp_transitively("BtnPrimary")
        assert result == sorted(result)
```

### Implementação (GREEN)

```python
# src/design_graph/graph/reader.py — substituir find_screens_using_comp_transitively

def find_screens_using_comp_transitively(self, comp_name: str) -> list[str]:
    rows = self._q(
        "MATCH (s:Screen)-[:USES_COMPONENT]->(p:Component)"
        "-[:CONTAINS*0..3]->(c:Component {name:$n}) "
        "RETURN DISTINCT s.name ORDER BY s.name",
        {"n": comp_name},
    )
    logger.debug(
        "reader: find_screens_transitively(%s) → %d screens",
        comp_name,
        len(rows),
    )
    return [r["s.name"] for r in rows]
```

---

## Done when

- [ ] Todos os 6 testes acima passam
- [ ] `get_impact("Badge")` retorna as telas corretas (integração via `get_impact`)
- [ ] Nenhum `CREATE`, `DELETE` ou `MERGE` em `reader.py` (G3)
- [ ] Log de debug registra componente + contagem de telas encontradas
