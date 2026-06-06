# T20 — Aresta `STYLE_USES_TOKEN` (Style → Token)

**Change**: C09 — Style-Level Token Linkage
**Arquivos**:
  - `src/design_graph/graph/schema.py`
  - `src/design_graph/graph/writer.py`
  - `src/design_graph/graph/reader.py`
**Depende de**: T09 (schema), T10 (writer), T11 (reader)
**Bloqueia**: enriquecimento de `get_component_spec` (C08 fase final)

---

## O que muda

### schema.py

```python
# Adicionar em _REL_TABLES (após USES_TOKEN)
"CREATE REL TABLE STYLE_USES_TOKEN(FROM Style TO Token)",
```

Atualizar `_REL_TABLES` test em `test_schema_and_diff.py`:
```python
"STYLE_USES_TOKEN",  # adicionar à lista
```

### writer.py

```python
def _link_style_to_token(
    self,
    style: StyleEntry,
    token_map: dict[str, list[DesignToken]],
) -> None:
    normalized = style.value.strip().lower()
    for tokens in token_map.values():
        for token in tokens:
            if normalized == token.value.lower() or token.value.lower() in normalized:
                self._safe_execute(
                    "MATCH (s:Style {id:$sid}),(t:Token {id:$tid}) "
                    "CREATE (s)-[:STYLE_USES_TOKEN]->(t)",
                    {"sid": style.id, "tid": token.id},
                )
                return
```

Chamar em `write_component()` logo após cada `HAS_STYLE` inserido:
```python
for style in comp.styles:
    self._safe_execute(...)  # insere Style node
    self._safe_execute(...)  # cria HAS_STYLE
    self._link_style_to_token(style, token_map)  # NOVO
```

`token_map` já é passado como parâmetro em `write_component(comp, token_map)` —
a assinatura não muda.

### reader.py

```python
def get_styles_with_tokens(self, comp_name: str) -> list[dict]:
    resolved = self._fuzzy_find_component(comp_name)
    if not resolved:
        return []
    return self._q(
        "MATCH (c:Component {name:$n})-[:HAS_STYLE]->(s:Style) "
        "OPTIONAL MATCH (s)-[:STYLE_USES_TOKEN]->(t:Token) "
        "RETURN s.state, s.property, s.value, "
        "       t.label AS token_label, t.value AS token_value, t.category AS token_category "
        "ORDER BY s.state, s.property",
        {"n": resolved},
    )
```

---

## TDD

### Schema tests (RED → GREEN)

```python
def test_style_uses_token_in_schema_ddl():
    from design_graph.graph.schema import SCHEMA
    assert any("STYLE_USES_TOKEN" in s for s in SCHEMA)

def test_style_uses_token_rel_created(fresh_conn):
    initialize_schema(fresh_conn)
    fresh_conn.execute("MATCH ()-[r:STYLE_USES_TOKEN]->() RETURN count(r)")
```

### Writer tests (RED → GREEN)

```python
class TestStyleTokenLinkage:
    @pytest.fixture
    def writer_with_data(self, tmp_path):
        db = kuzu.Database(str(tmp_path / "t.db"))
        conn = kuzu.Connection(db)
        initialize_schema(conn)
        return GraphWriter(conn), conn

    def test_creates_style_uses_token_when_value_matches(self, writer_with_data):
        writer, conn = writer_with_data
        token = DesignToken(id="tok1", category="color", label="primary",
                            value="#ffb81c", usage=5)
        writer.write_tokens([token])
        comp = ExtractedComponent(
            name="Btn", comp_type="button", jsx_snippet="", occurrence=1,
            classes="", child_refs=[],
            styles=[StyleEntry(id="st1", element="Btn", state="default",
                               property="backgroundColor", value="#ffb81c")],
            interactions=[], texts=[],
        )
        writer.write_component(comp, {"color": [token]})
        result = conn.execute(
            "MATCH (s:Style)-[:STYLE_USES_TOKEN]->(t:Token) RETURN s.property, t.label"
        )
        assert result.has_next()
        row = result.get_next()
        assert row[0] == "backgroundColor"
        assert row[1] == "primary"

    def test_no_link_when_no_token_matches(self, writer_with_data):
        writer, conn = writer_with_data
        comp = ExtractedComponent(
            name="Btn", comp_type="button", jsx_snippet="", occurrence=1,
            classes="", child_refs=[],
            styles=[StyleEntry(id="st2", element="Btn", state="default",
                               property="fontSize", value="14px")],
            interactions=[], texts=[],
        )
        writer.write_component(comp, {})
        result = conn.execute("MATCH ()-[:STYLE_USES_TOKEN]->() RETURN count(*)")
        assert result.get_next()[0] == 0

    def test_at_most_one_link_per_style(self, writer_with_data):
        writer, conn = writer_with_data
        tokens = [
            DesignToken(id=f"t{i}", category="color", label=f"label{i}",
                        value="#ffb81c", usage=1)
            for i in range(3)
        ]
        writer.write_tokens(tokens)
        comp = ExtractedComponent(
            name="Btn2", comp_type="button", jsx_snippet="", occurrence=1,
            classes="", child_refs=[],
            styles=[StyleEntry(id="st3", element="Btn2", state="default",
                               property="backgroundColor", value="#ffb81c")],
            interactions=[], texts=[],
        )
        writer.write_component(comp, {"color": tokens})
        result = conn.execute(
            "MATCH (s:Style {id:'st3'})-[:STYLE_USES_TOKEN]->(t) RETURN count(t)"
        )
        assert result.get_next()[0] <= 1
```

### Reader tests (RED → GREEN)

```python
class TestGetStylesWithTokens:
    def test_returns_list(self, populated_reader):
        result = populated_reader.get_styles_with_tokens("BtnPrimary")
        assert isinstance(result, list)

    def test_each_row_has_state_property_value(self, populated_reader):
        for row in populated_reader.get_styles_with_tokens("BtnPrimary"):
            assert "s.state" in row
            assert "s.property" in row
            assert "s.value" in row

    def test_token_fields_present(self, populated_reader):
        for row in populated_reader.get_styles_with_tokens("BtnPrimary"):
            assert "token_label" in row
            assert "token_value" in row
            assert "token_category" in row

    def test_unknown_component_returns_empty(self, populated_reader):
        assert populated_reader.get_styles_with_tokens("NonExistent") == []
```

---

## Done when

- [ ] `STYLE_USES_TOKEN` presente em `SCHEMA` DDL
- [ ] `initialize_schema` cria a tabela sem erro
- [ ] `write_component` chama `_link_style_to_token` para cada style
- [ ] Matching é case-insensitive (test: `"#FFB81C"` casa com `"#ffb81c"`)
- [ ] No máximo 1 aresta `STYLE_USES_TOKEN` por Style (primeiro match vence)
- [ ] `get_styles_with_tokens` retorna `token_label` preenchido quando há match
- [ ] Todos os testes acima passam
- [ ] G3 guardrail: reader.py sem escrita
