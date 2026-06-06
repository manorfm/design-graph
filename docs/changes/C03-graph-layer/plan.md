# Plan 03 — Fase 3: Graph

## Objetivo

Separar schema, writer e reader em módulos distintos. Adicionar a relação
`CONTAINS`. Garantir que o writer é idempotente e que o reader é read-only.

## Pré-requisito

Fase 2 completa: `ExtractedComponent`, `ExtractedScreen`, `ExtractedSection`
disponíveis.

## Entregáveis

```
src/design_graph/graph/
  __init__.py
  schema.py
  writer.py
  reader.py
  diff.py
```

## Sequência TDD

### 3.1 `schema.py`

```python
class TestSchema:
    def test_schema_creates_all_tables(self, tmp_db):
        initialize_schema(tmp_db.conn)
        # Verificar que MATCH (n:Screen) não lança exceção
        # Verificar que MATCH ()-[:CONTAINS]->() não lança exceção

    def test_schema_is_idempotent(self, tmp_db):
        initialize_schema(tmp_db.conn)
        initialize_schema(tmp_db.conn)  # segunda chamada não deve explodir

    def test_contains_table_has_weight_property(self, tmp_db):
        # Inserir um CONTAINS e verificar que weight é armazenado
```

### 3.2 `writer.py`

```python
class TestGraphWriter:
    def test_write_token_inserts_node(self, writer):
        token = DesignToken(id="col_abc", category="color",
                            label="primary", value="#ffb81c", usage=5)
        writer.write_tokens([token])
        # MATCH (t:Token {id:'col_abc'}) → encontrado

    def test_write_component_inserts_node(self, writer):
        comp = make_extracted_component("BtnPrimary")
        writer.write_component(comp)
        # MATCH (c:Component {name:'BtnPrimary'}) → encontrado

    def test_write_component_idempotent(self, writer):
        comp = make_extracted_component("BtnPrimary")
        writer.write_component(comp)
        writer.write_component(comp)  # segunda vez — não duplica
        # count deve ser 1

    def test_write_component_creates_contains_rels(self, writer):
        # Componente com child_refs=['Badge', 'Icon']
        # Após write_component: CONTAINS rels criadas
        badge = make_extracted_component("Badge")
        icon = make_extracted_component("Icon")
        btn = make_extracted_component("BtnWithChildren", child_refs=["Badge", "Icon"])
        writer.write_component(badge)
        writer.write_component(icon)
        writer.write_component(btn)
        # MATCH (p:Component {name:'BtnWithChildren'})-[:CONTAINS]->(c)
        # RETURN c.name → ["Badge", "Icon"]

    def test_write_screen_creates_uses_component_rels(self, writer):
        # ...

    def test_write_creates_shell_component_for_unknown_ref(self, writer):
        # Screen referencia "UnknownComp" que não foi extraído como função
        # writer cria um componente "shell" com jsx_snippet=""
```

### 3.3 `reader.py`

```python
class TestGraphReader:
    def test_list_screens_returns_all(self, populated_db):
        reader = GraphReader(populated_db.conn)
        screens = reader.list_screens()
        assert any(s["name"] == "RestaurantsPage" for s in screens)

    def test_get_component_children_uses_contains(self, populated_db):
        # NOVO: aproveita CONTAINS
        reader = GraphReader(populated_db.conn)
        children = reader.get_component_children("BtnWithChildren")
        assert "Badge" in children

    def test_find_screens_using_comp_transitively(self, populated_db):
        # RestaurantsPage → SectionCard → Badge
        # find_screens_using_comp_transitively("Badge") deve retornar RestaurantsPage
        reader = GraphReader(populated_db.conn)
        screens = reader.find_screens_using_comp_transitively("Badge")
        assert "RestaurantsPage" in screens

    def test_fuzzy_get_screen(self, populated_db):
        # get_screen("Restaurants") → resolve para "RestaurantsPage"
        reader = GraphReader(populated_db.conn)
        result = reader.get_screen("Restaurants")
        assert result is not None
        assert result["name"] == "RestaurantsPage"
```

### 3.4 `diff.py`

Testes já cobertos pelo legado `test_build.py::TestDiffState`.
Migrar esses testes para `tests/unit/graph/test_diff.py` sem mudança de lógica.

## Fixture `populated_db`

```python
# tests/conftest.py

@pytest.fixture
def populated_db(tmp_path):
    """
    Cria um banco Kuzu temporário com dados mínimos para testar reader/writer.
    Não usa HTML real — insere entidades diretamente.
    """
    import kuzu
    db = kuzu.Database(str(tmp_path / "test.db"))
    conn = kuzu.Connection(db)
    initialize_schema(conn)
    writer = GraphWriter(conn)
    # Inserir Screen, Components, Tokens, etc.
    writer.write_tokens([DesignToken(...)])
    writer.write_component(...)
    writer.write_screen(...)
    # Retornar conn read-only
    ro_db = kuzu.Database(str(tmp_path / "test.db"), read_only=True)
    ro_conn = kuzu.Connection(ro_db)
    yield SimpleNamespace(conn=ro_conn, path=tmp_path / "test.db")
```

## Critério de aceite

```bash
pytest tests/unit/graph/ -v
# writer idempotente — sem duplicatas
# reader.get_component_children funciona
# reader.find_screens_using_comp_transitively funciona
```

## Guardrails desta fase

1. `reader.py` importa `kuzu` mas nunca chama `conn.execute()` com `CREATE`/`DELETE`
2. `writer.py` nunca abre um banco — recebe `conn` por injeção
3. `schema.py` contém apenas constantes e a função `initialize_schema` — sem lógica de negócio
4. `diff.py` não toca no Kuzu — opera apenas em dicts Python
