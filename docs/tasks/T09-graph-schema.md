# T09 — GraphSchema

**Fase**: 3 — Graph
**Arquivo**: `src/design_graph/graph/schema.py`
**Depende de**: nada (só constantes)
**Bloqueia**: T10 (GraphWriter), T11 (GraphReader)

---

## Contrato

```python
SCHEMA: list[str]  # lista de DDL statements

def initialize_schema(conn: kuzu.Connection) -> None:
    """
    Cria todas as tabelas. Silencia erros de "table already exists".
    Lança exceção para outros erros.
    """

STATS_QUERIES: dict[str, str]  # nome → cypher para contar cada tipo de nó
```

---

## TDD

```python
# tests/unit/graph/test_schema.py

@pytest.fixture
def fresh_conn(tmp_path):
    import kuzu
    db = kuzu.Database(str(tmp_path / "t.db"))
    return kuzu.Connection(db)


class TestInitializeSchema:
    def test_all_node_tables_created(self, fresh_conn):
        initialize_schema(fresh_conn)
        for table in ["Screen", "Component", "Token", "UIText", "Style",
                      "Interaction", "Section"]:
            # Verificar que MATCH não lança exceção
            fresh_conn.execute(f"MATCH (n:{table}) RETURN count(n)")

    def test_all_rel_tables_created(self, fresh_conn):
        initialize_schema(fresh_conn)
        for rel in ["USES_COMPONENT", "HAS_SECTION", "SECTION_USES", "HAS_STYLE",
                    "USES_TOKEN", "COMP_HAS_TEXT", "SCREEN_HAS_TEXT",
                    "HAS_INTERACTION", "CONTAINS"]:
            fresh_conn.execute(f"MATCH ()-[r:{rel}]->() RETURN count(r)")

    def test_contains_has_weight_property(self, fresh_conn):
        initialize_schema(fresh_conn)
        # Criar dois componentes e uma relação CONTAINS com weight
        fresh_conn.execute("CREATE (:Component {name:'Parent', comp_type:'card', "
                           "jsx_snippet:'', occurrence:1, classes:''})")
        fresh_conn.execute("CREATE (:Component {name:'Child', comp_type:'button', "
                           "jsx_snippet:'', occurrence:1, classes:''})")
        fresh_conn.execute(
            "MATCH (p:Component {name:'Parent'}),(c:Component {name:'Child'}) "
            "CREATE (p)-[:CONTAINS {weight:3}]->(c)"
        )
        result = fresh_conn.execute(
            "MATCH ()-[r:CONTAINS]->() RETURN r.weight"
        )
        assert result.get_next()[0] == 3

    def test_idempotent_second_call(self, fresh_conn):
        initialize_schema(fresh_conn)
        initialize_schema(fresh_conn)  # não deve lançar exceção

    def test_section_has_detection_method_field(self, fresh_conn):
        initialize_schema(fresh_conn)
        # Inserir Section com detection_method
        fresh_conn.execute(
            "CREATE (:Section {id:'s1', screen:'Pg', name:'Header', "
            "styles_json:'{}', components_json:'[]', texts_json:'[]', "
            "jsx_snippet:'', detection_method:'comment'})"
        )
        result = fresh_conn.execute("MATCH (s:Section {id:'s1'}) RETURN s.detection_method")
        assert result.get_next()[0] == "comment"


class TestStatsQueries:
    def test_all_stats_keys_present(self):
        expected = {"screens", "components", "tokens", "texts",
                    "styles", "sections", "interactions", "contains"}
        assert expected.issubset(set(STATS_QUERIES.keys()))

    def test_stats_queries_execute_on_empty_db(self, fresh_conn):
        initialize_schema(fresh_conn)
        for name, cypher in STATS_QUERIES.items():
            result = fresh_conn.execute(cypher)
            assert result.get_next()[0] == 0
```

---

## Done when

- [x] Todos os testes passam
- [x] `CONTAINS` inclui campo `weight INT64`
- [x] `Section` inclui campo `detection_method STRING`
- [x] `initialize_schema` é idempotente (2× sem erro)
