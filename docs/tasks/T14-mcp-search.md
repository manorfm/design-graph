# T14 — MCPSearch

**Fase**: 5 — MCP
**Arquivo**: `src/design_graph/mcp/search.py` + `src/design_graph/mcp/aliases.py`
**Depende de**: T11 (GraphReader)
**Bloqueia**: T15 (MCPTools)

---

## Contrato

```python
# aliases.py
ALIASES: dict[str, list[str]]
def get_aliases() -> dict[str, list[str]]: ...

# search.py
@dataclass
class SearchResult:
    type: str     # "Screen" | "Component" | "Token" | "UIText"
    name: str
    detail: str
    id: str
    doc: str
    score: int    # 0-100

def _score(name: str, query: str) -> int: ...
def _expand_query(query: str, aliases: dict) -> list[str]: ...

def search(
    readers: list[tuple[str, GraphReader]],
    query: str,
    max_results: int = 30,
) -> list[SearchResult]:
    """
    Busca cross-prototype com scoring. Retorna ordenado por score desc.
    Deduplicata por (doc, id).
    """
```

---

## TDD

```python
# tests/unit/mcp/test_search.py

class TestScore:
    @pytest.mark.parametrize("name,query,expected", [
        ("SectionCard",          "SectionCard",  100),  # exact
        ("SectionCard",          "Section",       80),  # prefix
        ("SectionCard",          "Card",          60),  # suffix
        ("RestaurantSectionCard","tionCard",      40),  # contains
        ("BtnPrimary",           "Modal",          0),  # no match
        ("",                     "test",           0),  # empty name
        ("BtnPrimary",           "",               0),  # empty query
    ])
    def test_score_cases(self, name, query, expected):
        assert _score(name, query) == expected

    def test_case_insensitive(self):
        assert _score("SectionCard", "sectioncard") == 100
        assert _score("SectionCard", "SECTION") == 80


class TestExpandQuery:
    def test_single_term_unchanged(self):
        terms = _expand_query("card", {})
        assert "card" in terms

    def test_alias_expanded(self):
        aliases = {"botão": ["Btn", "Button"]}
        terms = _expand_query("botão", aliases)
        assert "btn" in terms or "button" in terms

    def test_deduplicates(self):
        aliases = {"btn": ["Btn", "Button"]}
        terms = _expand_query("btn btn", aliases)
        assert terms.count("btn") == 1

    def test_max_6_terms(self):
        # Alias que expande para muitos termos
        aliases = {"big": [f"Term{i}" for i in range(20)]}
        terms = _expand_query("big", aliases)
        assert len(terms) <= 6

    def test_empty_query(self):
        terms = _expand_query("", {})
        assert terms == [""] or terms == []


class TestSearch:
    @pytest.fixture
    def mock_readers(self):
        """Dois readers mock com dados distintos."""
        ...

    def test_returns_sorted_by_score(self, mock_readers):
        results = search(mock_readers, "card")
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_deduplicates_by_doc_and_id(self, mock_readers):
        results = search(mock_readers, "SectionCard")
        ids = [(r.doc, r.id) for r in results]
        assert len(ids) == len(set(ids))

    def test_cross_prototype_results_include_doc(self, mock_readers):
        results = search(mock_readers, "card")
        # Resultados de docs diferentes aparecem com doc correto
        docs = {r.doc for r in results}
        assert len(docs) <= 2  # no máximo 2 docs no mock

    def test_max_results_respected(self, mock_readers):
        results = search(mock_readers, "a", max_results=5)
        assert len(results) <= 5

    def test_empty_query_returns_empty(self, mock_readers):
        results = search(mock_readers, "")
        assert results == []

    def test_alias_pt_finds_components(self, mock_readers):
        # "botão" deve encontrar componentes com "Btn" ou "Button" no nome
        results = search(mock_readers, "botão")
        names = [r.name for r in results]
        assert any("Btn" in n or "Button" in n for n in names)


class TestAliases:
    def test_get_aliases_returns_dict(self):
        aliases = get_aliases()
        assert isinstance(aliases, dict)

    def test_botao_key_exists(self):
        aliases = get_aliases()
        assert "botão" in aliases or "botao" in aliases

    def test_returned_dict_is_copy(self):
        a = get_aliases()
        b = get_aliases()
        a["injected_key"] = []
        assert "injected_key" not in b
```

---

## Mock para testes de search

```python
class MockReader:
    def __init__(self, comps=None, screens=None):
        self._comps = comps or [{"name": "SectionCard", "comp_type": "card"}]
        self._screens = screens or [{"name": "RestaurantsPage"}]
        self._tokens = [{"label": "primary", "value": "#ffb81c", "id": "col_1"}]
        self._texts = []

    def list_screens(self): return self._screens
    def get_component(self, name): return next((c for c in self._comps if c["name"]==name), None)
    # Métodos de busca retornam dados filtrados para os testes
    def _search_components(self, q):
        return [c for c in self._comps if q.lower() in c["name"].lower()]
    # ... etc
```

---

## Done when

- [ ] `_score("SectionCard", "SectionCard") == 100`
- [ ] `_score("SectionCard", "Section") == 80`
- [ ] `_score("SectionCard", "Modal") == 0`
- [ ] `search(readers, "botão")` retorna BtnPrimary via alias PT
- [ ] Resultados ordenados por score desc
