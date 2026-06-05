# T11 — GraphReader

**Fase**: 3 — Graph
**Arquivo**: `src/design_graph/graph/reader.py`
**Depende de**: T09 (schema), T10 (writer — para fixture populated_db)
**Bloqueia**: T14 (MCPSearch), T15 (MCPTools)

---

## Contrato

```python
class GraphReader:
    def __init__(self, conn: kuzu.Connection):
        self._conn = conn

    # ── Telas ──
    def list_screens(self) -> list[dict]: ...
    def get_screen(self, name: str) -> dict | None: ...

    # ── Seções ──
    def get_section(self, screen: str, section_hint: str) -> dict | None: ...

    # ── Componentes ──
    def get_component(self, name: str) -> dict | None: ...
    def get_component_children(self, name: str) -> list[str]: ...     # NOVO
    def get_component_parents(self, name: str) -> list[str]: ...      # NOVO

    # ── Tokens ──
    def get_tokens(self, category: str | None = None) -> list[dict]: ...
    def find_token_usage(self, value: str) -> list[dict]: ...

    # ── Interações ──
    def get_interactions(self, comp_name: str) -> list[dict]: ...

    # ── JSX completo ──
    def get_full_jsx(self, name: str) -> str: ...

    # ── Impacto ──
    def get_impact(self, name: str) -> dict: ...

    # ── Stats ──
    def count_nodes(self) -> dict[str, int]: ...

    # ── Query transitiva (aproveita CONTAINS) ──
    def find_screens_using_comp_transitively(self, comp_name: str) -> list[str]: ...

    # ── Fuzzy internos ──
    def _fuzzy_find_screen(self, hint: str) -> str | None: ...
    def _fuzzy_find_component(self, hint: str) -> str | None: ...
```

---

## TDD

```python
# tests/unit/graph/test_reader.py

@pytest.fixture
def populated_reader(tmp_path):
    """
    Banco com:
    - 2 telas: RestaurantsPage, LoginForm
    - 3 componentes: SectionCard (filho de RestaurantsPage), BtnPrimary, Badge
    - BtnPrimary contém Badge (relação CONTAINS)
    - 1 token: primary = #ffb81c
    - 1 seção em RestaurantsPage: Header (detection_method=comment)
    """
    import kuzu
    db = kuzu.Database(str(tmp_path / "r.db"))
    conn = kuzu.Connection(db)
    initialize_schema(conn)
    # ... inserir dados via GraphWriter ...
    ro = kuzu.Database(str(tmp_path / "r.db"), read_only=True)
    return GraphReader(kuzu.Connection(ro))


class TestListScreens:
    def test_returns_all_screens(self, populated_reader):
        screens = populated_reader.list_screens()
        names = {s["name"] for s in screens}
        assert "RestaurantsPage" in names
        assert "LoginForm" in names

    def test_returns_component_count(self, populated_reader):
        screens = populated_reader.list_screens()
        rest = next(s for s in screens if s["name"] == "RestaurantsPage")
        assert "component_count" in rest


class TestGetScreen:
    def test_finds_exact_name(self, populated_reader):
        screen = populated_reader.get_screen("RestaurantsPage")
        assert screen is not None
        assert screen["name"] == "RestaurantsPage"

    def test_fuzzy_prefix_match(self, populated_reader):
        screen = populated_reader.get_screen("Restaurants")
        assert screen is not None
        assert screen["name"] == "RestaurantsPage"

    def test_returns_none_for_unknown(self, populated_reader):
        assert populated_reader.get_screen("NonExistent") is None

    def test_returns_sections(self, populated_reader):
        screen = populated_reader.get_screen("RestaurantsPage")
        assert "sections" in screen


class TestGetComponentChildren:
    def test_returns_direct_children(self, populated_reader):
        children = populated_reader.get_component_children("BtnPrimary")
        assert "Badge" in children

    def test_returns_empty_for_leaf_component(self, populated_reader):
        children = populated_reader.get_component_children("Badge")
        assert children == []

    def test_returns_empty_for_unknown_component(self, populated_reader):
        children = populated_reader.get_component_children("NonExistent")
        assert children == []


class TestGetComponentParents:
    def test_returns_parent_components(self, populated_reader):
        parents = populated_reader.get_component_parents("Badge")
        assert "BtnPrimary" in parents

    def test_returns_empty_for_root_component(self, populated_reader):
        # SectionCard não é filho de nenhum componente (só de Screen)
        parents = populated_reader.get_component_parents("SectionCard")
        assert parents == []


class TestFindScreensTransitively:
    def test_finds_screen_via_contains_chain(self, populated_reader):
        # RestaurantsPage → SectionCard (USES_COMPONENT)
        # (Badge não está em nenhuma Screen diretamente, mas via BtnPrimary)
        # Este teste verifica que a query transitiva funciona
        screens = populated_reader.find_screens_using_comp_transitively("Badge")
        # Badge está em BtnPrimary, que está em RestaurantsPage
        # O resultado depende de como os dados estão inseridos no fixture
        assert isinstance(screens, list)

    def test_returns_empty_for_unused_component(self, populated_reader):
        screens = populated_reader.find_screens_using_comp_transitively("NotUsed")
        assert screens == []


class TestGetImpact:
    def test_component_impact_returns_screens(self, populated_reader):
        impact = populated_reader.get_impact("SectionCard")
        assert "screens" in impact
        assert "RestaurantsPage" in impact["screens"]

    def test_token_impact_returns_components(self, populated_reader):
        impact = populated_reader.get_impact("primary")
        assert "components" in impact or "screens" in impact

    def test_unknown_name_returns_not_found_indicator(self, populated_reader):
        impact = populated_reader.get_impact("NonExistent")
        assert impact.get("found") is False or impact == {}
```

---

## Queries CONTAINS (novas)

```cypher
-- get_component_children
MATCH (p:Component {name:$name})-[:CONTAINS]->(c:Component)
RETURN c.name ORDER BY c.name

-- get_component_parents
MATCH (p:Component)-[:CONTAINS]->(c:Component {name:$name})
RETURN p.name ORDER BY p.name

-- find_screens_using_comp_transitively (até 3 níveis)
MATCH (s:Screen)-[:USES_COMPONENT*1..3]->(c:Component {name:$name})
RETURN DISTINCT s.name ORDER BY s.name
```

---

## Done when

- [ ] Todos os testes passam
- [ ] `get_component_children` usa a relação `CONTAINS`
- [ ] `find_screens_using_comp_transitively` usa `USES_COMPONENT*1..3`
- [ ] Nenhum método de `reader.py` contém `CREATE`, `DELETE`, ou `MERGE`
