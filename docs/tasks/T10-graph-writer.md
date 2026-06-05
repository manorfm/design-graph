# T10 — GraphWriter

**Fase**: 3 — Graph
**Arquivo**: `src/design_graph/graph/writer.py`
**Depende de**: T09 (schema), T06 (ExtractedComponent), T07 (ExtractedScreen), T08 (ExtractedSection), T04 (DesignToken)
**Bloqueia**: T13 (PipelineCoordinator)

---

## Contrato

```python
class GraphWriter:
    def __init__(self, conn: kuzu.Connection):
        self._conn = conn
        self._inserted_comps: set[str] = set()
        self._inserted_style_ids: set[str] = set()
        self._inserted_inter_ids: set[str] = set()
        self._inserted_text_ids: set[str] = set()
        self._token_rels_done: set[str] = set()
        self._contains_done: set[str] = set()

    @property
    def inserted_names(self) -> frozenset[str]:
        """Nomes de componentes já inseridos (read-only)."""

    def write_tokens(self, tokens: list[DesignToken]) -> int:
        """Retorna count de tokens inseridos."""

    def write_component(
        self,
        comp: ExtractedComponent,
        token_map: dict[str, list[DesignToken]],
    ) -> None:
        """Insere Component + filhos: Style, Interaction, UIText + CONTAINS."""

    def write_screen(
        self,
        screen: ExtractedScreen,
        sections: list[ExtractedSection],
        token_map: dict[str, list[DesignToken]],
    ) -> None:
        """Insere Screen + USES_COMPONENT + Sections + SECTION_USES."""

    def get_stats(self) -> dict[str, int]:
        """Executa STATS_QUERIES e retorna contagens."""
```

---

## TDD

```python
# tests/unit/graph/test_writer.py

@pytest.fixture
def writer(tmp_path):
    import kuzu
    db = kuzu.Database(str(tmp_path / "w.db"))
    conn = kuzu.Connection(db)
    initialize_schema(conn)
    return GraphWriter(conn), conn


class TestWriteTokens:
    def test_inserts_token_node(self, writer):
        gw, conn = writer
        token = DesignToken(id="col_1", category="color",
                            label="primary", value="#ffb81c", usage=5)
        count = gw.write_tokens([token])
        assert count == 1
        result = conn.execute("MATCH (t:Token {id:'col_1'}) RETURN t.label")
        assert result.get_next()[0] == "primary"

    def test_idempotent_duplicate_token(self, writer):
        gw, conn = writer
        token = DesignToken(id="col_1", category="color",
                            label="primary", value="#ffb81c", usage=5)
        gw.write_tokens([token])
        gw.write_tokens([token])  # segunda vez
        result = conn.execute("MATCH (t:Token) RETURN count(t)")
        assert result.get_next()[0] == 1


class TestWriteComponent:
    def _make_comp(self, name, child_refs=None):
        return ExtractedComponent(
            name=name, comp_type="card", jsx_snippet="<div/>",
            occurrence=1, classes="", styles=[], interactions=[],
            texts=[], child_refs=child_refs or []
        )

    def test_inserts_component_node(self, writer):
        gw, conn = writer
        gw.write_component(self._make_comp("BtnPrimary"), {})
        result = conn.execute("MATCH (c:Component {name:'BtnPrimary'}) RETURN c.name")
        assert result.get_next()[0] == "BtnPrimary"

    def test_idempotent_duplicate_component(self, writer):
        gw, conn = writer
        gw.write_component(self._make_comp("BtnPrimary"), {})
        gw.write_component(self._make_comp("BtnPrimary"), {})
        result = conn.execute("MATCH (c:Component) RETURN count(c)")
        assert result.get_next()[0] == 1

    def test_creates_contains_relation(self, writer):
        gw, conn = writer
        gw.write_component(self._make_comp("Badge"), {})
        gw.write_component(self._make_comp("BtnWithBadge", child_refs=["Badge"]), {})
        result = conn.execute(
            "MATCH (p:Component {name:'BtnWithBadge'})-[:CONTAINS]->(c:Component) "
            "RETURN c.name"
        )
        assert result.get_next()[0] == "Badge"

    def test_contains_not_created_if_child_missing(self, writer):
        gw, conn = writer
        # "UnknownChild" não foi inserido antes
        gw.write_component(self._make_comp("Orphan", child_refs=["UnknownChild"]), {})
        result = conn.execute("MATCH ()-[:CONTAINS]->() RETURN count(*)")
        assert result.get_next()[0] == 0

    def test_style_linked_to_component(self, writer):
        gw, conn = writer
        style = StyleEntry(id="st_1", element="BtnPrimary", state="default",
                           property="backgroundColor", value="#ffb81c")
        comp = ExtractedComponent(
            name="BtnPrimary", comp_type="button", jsx_snippet="",
            occurrence=1, classes="", styles=[style], interactions=[], texts=[], child_refs=[]
        )
        gw.write_component(comp, {})
        result = conn.execute(
            "MATCH (c:Component {name:'BtnPrimary'})-[:HAS_STYLE]->(s:Style) "
            "RETURN s.property"
        )
        assert result.get_next()[0] == "backgroundColor"

    def test_token_rel_created_when_style_value_matches_token(self, writer):
        gw, conn = writer
        token = DesignToken(id="col_1", category="color",
                            label="primary", value="#ffb81c", usage=5)
        gw.write_tokens([token])
        token_map = build_token_map([token])
        style = StyleEntry(id="st_1", element="BtnPrimary", state="default",
                           property="backgroundColor", value="#ffb81c")
        comp = ExtractedComponent(
            name="BtnPrimary", comp_type="button", jsx_snippet="",
            occurrence=1, classes="", styles=[style], interactions=[], texts=[], child_refs=[]
        )
        gw.write_component(comp, token_map)
        result = conn.execute(
            "MATCH (c:Component {name:'BtnPrimary'})-[:USES_TOKEN]->(t:Token) "
            "RETURN t.label"
        )
        assert result.get_next()[0] == "primary"


class TestWriteScreen:
    def test_inserts_screen_node(self, writer):
        gw, conn = writer
        screen = ExtractedScreen(name="RestaurantsPage",
                                 component_refs=[], sections_count=0)
        gw.write_screen(screen, [], {})
        result = conn.execute(
            "MATCH (s:Screen {name:'RestaurantsPage'}) RETURN s.name"
        )
        assert result.get_next()[0] == "RestaurantsPage"

    def test_creates_shell_component_for_unknown_ref(self, writer):
        gw, conn = writer
        screen = ExtractedScreen(name="RestaurantsPage",
                                 component_refs=["UnknownComp"], sections_count=0)
        gw.write_screen(screen, [], {})
        result = conn.execute(
            "MATCH (c:Component {name:'UnknownComp'}) RETURN c.jsx_snippet"
        )
        assert result.get_next()[0] == ""  # shell: jsx vazio

    def test_section_linked_to_screen(self, writer):
        gw, conn = writer
        screen = ExtractedScreen(name="RestaurantsPage",
                                 component_refs=[], sections_count=1)
        section = ExtractedSection(
            id="sec_1", screen="RestaurantsPage", name="Header",
            styles={}, component_refs=[], texts=[], jsx_snippet="<div/>",
            detection_method="comment"
        )
        gw.write_screen(screen, [section], {})
        result = conn.execute(
            "MATCH (s:Screen {name:'RestaurantsPage'})-[:HAS_SECTION]->(sec:Section) "
            "RETURN sec.name"
        )
        assert result.get_next()[0] == "Header"


class TestGetStats:
    def test_returns_all_keys(self, writer):
        gw, _ = writer
        stats = gw.get_stats()
        assert "screens" in stats
        assert "components" in stats
        assert "contains" in stats  # NOVO

    def test_stats_are_zero_for_empty_db(self, writer):
        gw, _ = writer
        stats = gw.get_stats()
        assert all(v == 0 for v in stats.values())
```

---

## Done when

- [ ] Todos os testes passam
- [ ] `write_component` nunca cria relação `CONTAINS` para filho que não existe
- [ ] `inserted_names` é read-only (frozenset)
- [ ] `get_stats()` inclui chave `"contains"`
