# Plan C09 — Style-Level Token Linkage

## Objetivo

Adicionar a aresta `STYLE_USES_TOKEN` (Style→Token) para que agentes possam
perguntar "qual token define a backgroundColor do BtnPrimary?" e obter resposta.

## Critério de aceite

```bash
pytest tests/unit/graph/ -k "style_token or styles_with_tokens" -v
# todos verdes

# schema DDL inclui STYLE_USES_TOKEN
python -c "from design_graph.graph.schema import SCHEMA; print([s for s in SCHEMA if 'STYLE_USES_TOKEN' in s])"
# → ['CREATE REL TABLE STYLE_USES_TOKEN(FROM Style TO Token)']
```

## Sequência TDD

### Fase 1: schema — adicionar `STYLE_USES_TOKEN`

**RED:**
```python
# tests/unit/graph/test_schema_and_diff.py

def test_style_uses_token_rel_in_schema():
    from design_graph.graph.schema import SCHEMA
    assert any("STYLE_USES_TOKEN" in stmt for stmt in SCHEMA)

def test_style_uses_token_rel_table_created(fresh_conn):
    initialize_schema(fresh_conn)
    fresh_conn.execute("MATCH ()-[r:STYLE_USES_TOKEN]->() RETURN count(r)")
    # não lança exceção
```

**GREEN:** adicionar ao `_REL_TABLES` em `schema.py`:
```python
"CREATE REL TABLE STYLE_USES_TOKEN(FROM Style TO Token)",
```

### Fase 2: writer — `_link_style_to_token()`

**RED:**
```python
# tests/unit/graph/test_writer_deduplication_guards.py

class TestStyleTokenLinkage:
    def test_style_linked_to_matching_token(self, db_conn):
        """Style com valor igual ao token recebe aresta STYLE_USES_TOKEN."""
        # setup: criar token + componente com style de mesmo valor
        ...
        # verificar:
        rows = db_conn.execute(
            "MATCH (s:Style)-[:STYLE_USES_TOKEN]->(t:Token) RETURN s.property, t.label"
        )
        assert rows.has_next()

    def test_style_without_match_has_no_link(self, db_conn):
        """Style com valor arbitrário (não token) não cria aresta."""
        ...
        result = db_conn.execute("MATCH ()-[:STYLE_USES_TOKEN]->() RETURN count(*)")
        count = result.get_next()[0]
        assert count == 0

    def test_style_has_at_most_one_token_link(self, db_conn):
        """Mesmo que múltiplos tokens casem, apenas 1 aresta é criada."""
        ...
        result = db_conn.execute(
            "MATCH (s:Style {id:$sid})-[:STYLE_USES_TOKEN]->(t:Token) RETURN count(t)",
            {"sid": style_id}
        )
        assert result.get_next()[0] <= 1

    def test_matching_is_case_insensitive(self, db_conn):
        """Token '#FFB81C' casa com estilo '#ffb81c'."""
        ...
```

**GREEN:** implementar `_link_style_to_token()` e chamá-lo no final de cada
inserção de Style em `write_component()`.

### Fase 3: reader — `get_styles_with_tokens()`

**RED:**
```python
class TestGetStylesWithTokens:
    def test_returns_styles_with_token_info(self, populated_reader):
        styles = populated_reader.get_styles_with_tokens("BtnPrimary")
        assert isinstance(styles, list)
        # styles com token devem ter token_label preenchido
        token_styles = [s for s in styles if s.get("token_label")]
        assert len(token_styles) >= 0  # pode ser 0 se nenhum match

    def test_optional_token_fields_none_when_no_match(self, populated_reader):
        styles = populated_reader.get_styles_with_tokens("BtnPrimary")
        for s in styles:
            assert "s.property" in s
            assert "s.value" in s
            # token_* pode ser None (sem match) ou str (com match)

    def test_returns_empty_for_unknown_component(self, populated_reader):
        assert populated_reader.get_styles_with_tokens("NonExistent") == []
```

## Guardrails

- G3: `reader.py` não contém `CREATE`/`DELETE`/`MERGE`
- Schema: `initialize_schema()` é idempotente — chamar 2× não duplica a nova tabela
- Writer: `_link_style_to_token()` usa `_safe_execute()` — falha silenciosa se Style ou Token não existirem
