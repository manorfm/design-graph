# Plan C08 — MCP: Tools de Descoberta de Componentes

## Objetivo

Adicionar `list_components` e `get_component_spec` ao reader e ao MCP, permitindo
que agentes de IA descubram e inspecionem componentes de forma eficiente.

## Critério de aceite

```bash
pytest tests/unit/graph/test_reader_advanced_queries.py -k "list_components or component_spec" -v
pytest tests/unit/mcp/test_tools.py -k "list_components or component_spec" -v
# todos verdes
```

## Sequência TDD

### Fase 1: reader — `list_components()`

**RED — testes:**
```python
class TestListComponents:
    def test_returns_all_components(self, populated_reader):
        comps = populated_reader.list_components()
        names = {c["name"] for c in comps}
        assert "BtnPrimary" in names
        assert "Badge" in names

    def test_filter_by_comp_type(self, populated_reader):
        buttons = populated_reader.list_components(comp_type="button")
        assert all(c["comp_type"] == "button" for c in buttons)
        assert any(c["name"] == "BtnPrimary" for c in buttons)

    def test_unknown_type_returns_empty(self, populated_reader):
        result = populated_reader.list_components(comp_type="unknown_xyz")
        assert result == []

    def test_each_entry_has_required_fields(self, populated_reader):
        comps = populated_reader.list_components()
        for c in comps:
            assert "name" in c
            assert "comp_type" in c
            assert "occurrence" in c

    def test_sorted_by_occurrence_desc(self, populated_reader):
        comps = populated_reader.list_components()
        occs = [c["occurrence"] for c in comps]
        assert occs == sorted(occs, reverse=True)
```

**GREEN — implementação:**
```python
def list_components(self, comp_type: str | None = None) -> list[dict]:
    if comp_type:
        return self._q(
            "MATCH (c:Component {comp_type:$t}) "
            "RETURN c.name, c.comp_type, c.occurrence "
            "ORDER BY c.occurrence DESC",
            {"t": comp_type},
        )
    return self._q(
        "MATCH (c:Component) "
        "RETURN c.name, c.comp_type, c.occurrence "
        "ORDER BY c.occurrence DESC"
    )
```

### Fase 2: reader — `get_component_spec()`

**RED — testes:**
```python
class TestGetComponentSpec:
    def test_returns_none_for_unknown(self, populated_reader):
        assert populated_reader.get_component_spec("NonExistent") is None

    def test_returns_component_metadata(self, populated_reader):
        spec = populated_reader.get_component_spec("BtnPrimary")
        assert spec["name"] == "BtnPrimary"
        assert "comp_type" in spec
        assert "occurrence" in spec

    def test_returns_styles_grouped_by_state(self, populated_reader):
        spec = populated_reader.get_component_spec("BtnPrimary")
        assert "styles_by_state" in spec
        assert "default" in spec["styles_by_state"]

    def test_returns_tokens(self, populated_reader):
        spec = populated_reader.get_component_spec("BtnPrimary")
        assert "tokens" in spec
        assert isinstance(spec["tokens"], list)

    def test_returns_children(self, populated_reader):
        spec = populated_reader.get_component_spec("BtnPrimary")
        assert "children" in spec

    def test_returns_parents(self, populated_reader):
        spec = populated_reader.get_component_spec("Badge")
        assert "parents" in spec

    def test_returns_screens_using(self, populated_reader):
        spec = populated_reader.get_component_spec("BtnPrimary")
        assert "screens_using" in spec
        assert isinstance(spec["screens_using"], list)

    def test_returns_interactions(self, populated_reader):
        spec = populated_reader.get_component_spec("BtnPrimary")
        assert "interactions" in spec

    def test_returns_texts(self, populated_reader):
        spec = populated_reader.get_component_spec("BtnPrimary")
        assert "texts" in spec

    def test_returns_jsx_snippet(self, populated_reader):
        spec = populated_reader.get_component_spec("BtnPrimary")
        assert "jsx_snippet" in spec

    def test_fuzzy_name_resolution(self, populated_reader):
        spec = populated_reader.get_component_spec("btn")  # prefix match
        assert spec is not None
```

**GREEN — implementação:**
```python
def get_component_spec(self, name: str) -> dict | None:
    resolved = self._fuzzy_find_component(name)
    if not resolved:
        return None

    rows = self._q(
        "MATCH (c:Component {name:$n}) "
        "RETURN c.name, c.comp_type, c.jsx_snippet, c.occurrence, c.classes",
        {"n": resolved},
    )
    if not rows:
        return None
    comp = rows[0]

    styles = self._q(
        "MATCH (c:Component {name:$n})-[:HAS_STYLE]->(s:Style) "
        "RETURN s.state, s.property, s.value ORDER BY s.state, s.property",
        {"n": resolved},
    )
    styles_by_state: dict[str, list[dict]] = {}
    for s in styles:
        bucket = styles_by_state.setdefault(s["s.state"], [])
        bucket.append({"property": s["s.property"], "value": s["s.value"]})

    tokens = self._q(
        "MATCH (c:Component {name:$n})-[:USES_TOKEN]->(t:Token) "
        "RETURN t.label, t.value, t.category ORDER BY t.category",
        {"n": resolved},
    )
    texts = self._q(
        "MATCH (c:Component {name:$n})-[:COMP_HAS_TEXT]->(t:UIText) "
        "RETURN t.content, t.text_type, t.element ORDER BY t.text_type",
        {"n": resolved},
    )
    interactions = self._q(
        "MATCH (c:Component {name:$n})-[:HAS_INTERACTION]->(i:Interaction) "
        "RETURN i.trigger, i.css_prop, i.from_val, i.to_val, i.transition",
        {"n": resolved},
    )
    screens_using = self._q(
        "MATCH (s:Screen)-[:USES_COMPONENT]->(p:Component)"
        "-[:CONTAINS*0..1]->(c:Component {name:$n}) "
        "RETURN DISTINCT s.name ORDER BY s.name",
        {"n": resolved},
    )

    return {
        **comp,
        "styles_by_state":  styles_by_state,
        "tokens":           tokens,
        "texts":            texts[:15],
        "interactions":     interactions,
        "children":         self.get_component_children(resolved),
        "parents":          self.get_component_parents(resolved),
        "screens_using":    [r["s.name"] for r in screens_using],
    }
```

### Fase 3: MCP tools

**RED — testes:**
```python
class TestListComponentsTool:
    def test_returns_markdown_string(self, dispatcher):
        result = dispatcher.dispatch("list_components", {}, "doc1")
        assert isinstance(result, str) and len(result) > 0

    def test_filter_by_type_in_output(self, dispatcher):
        result = dispatcher.dispatch("list_components", {"comp_type": "button"}, "doc1")
        assert "button" in result.lower()

    def test_tool_in_definitions(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "list_components" in names

class TestGetComponentSpecTool:
    def test_returns_markdown_string(self, dispatcher):
        result = dispatcher.dispatch("get_component_spec", {"name": "BtnPrimary"}, "doc1")
        assert isinstance(result, str)

    def test_not_found_returns_error_string(self, dispatcher):
        result = dispatcher.dispatch("get_component_spec", {"name": "NonExistent"}, "doc1")
        assert "not found" in result.lower() or "nonexistent" in result.lower()

    def test_tool_in_definitions(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "get_component_spec" in names
```

## Guardrails a verificar

- G3: nenhum `CREATE`/`DELETE`/`MERGE` em `reader.py`
- G9: `tools.py` não importa de `graph/` no nível do módulo (importa via parâmetro `reader`)
- Cada nova tool deve ter `description` com > 20 caracteres em `TOOL_DEFINITIONS`
