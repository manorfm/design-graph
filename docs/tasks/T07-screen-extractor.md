# T07 — ScreenExtractor

**Fase**: 2 — Extraction
**Arquivo**: `src/design_graph/extraction/screen_extractor.py`
**Depende de**: T03 (FunctionBoundary), `core/patterns.py`, `core/constants.py`
**Bloqueia**: T08 (SectionExtractor), T10 (GraphWriter)

---

## Contrato

```python
@dataclass
class ExtractedScreen:
    name: str
    component_refs: list[str]   # componentes referenciados diretamente
    sections_count: int = 0     # preenchido após section_extractor rodar

def extract_screens(
    js: str,
    all_boundaries: list[FunctionBoundary],
) -> list[ExtractedScreen]:
    """
    Filtra boundaries que são telas (nome satisfaz RE_SCREEN_NAME).
    Para cada tela, coleta referências de componentes no corpo.
    """

def is_screen(name: str) -> bool:
    """Retorna True se o nome satisfaz o critério de Screen."""
```

---

## Critério de Screen

```python
# em core/patterns.py
RE_SCREEN_NAME = re.compile(
    r'^[A-Z][a-zA-Z]+'
    r'(?:Page|Screen|Dashboard|Detail|Panel|View|Tab|Section|List|Form|Modal)$'
)
```

**Exemplos positivos**: `RestaurantsPage`, `OrdersDashboard`, `MenuSection`, `LoginForm`
**Exemplos negativos**: `BtnPrimary`, `SectionCard`, `useRestaurants`, `Fragment`

---

## TDD

```python
# tests/unit/extraction/test_screen_extractor.py

class TestIsScreen:
    @pytest.mark.parametrize("name,expected", [
        ("RestaurantsPage",   True),
        ("OrdersDashboard",   True),
        ("MenuSection",       True),
        ("ItemDetail",        True),
        ("LoginForm",         True),
        ("ProfileModal",      True),
        ("BtnPrimary",        False),
        ("SectionCard",       False),
        ("useRestaurants",    False),
        ("Fragment",          False),
        ("RestaurantsPageHelper", False),  # nome que não termina em Screen keyword
    ])
    def test_is_screen(self, name, expected):
        assert is_screen(name) == expected


SCREENS_JS = """
function RestaurantsPage() {
    return (
        <div>
            <SectionCard restaurant={r} />
            <BtnPrimary onClick={handleOrder} />
            <ConfirmModal isOpen={open} />
        </div>
    )
}
function LoginForm() {
    return (
        <form>
            <Input name="email" />
            <BtnPrimary type="submit" />
        </form>
    )
}
function BtnPrimary() {
    return (<button>OK</button>)
}
"""


class TestExtractScreens:
    def test_finds_page_screens(self):
        from design_graph.parsing.js_parser import find_all_boundaries
        bounds = find_all_boundaries(SCREENS_JS)
        screens = extract_screens(SCREENS_JS, bounds)
        names = {s.name for s in screens}
        assert "RestaurantsPage" in names
        assert "LoginForm" in names

    def test_excludes_non_screens(self):
        from design_graph.parsing.js_parser import find_all_boundaries
        bounds = find_all_boundaries(SCREENS_JS)
        screens = extract_screens(SCREENS_JS, bounds)
        names = {s.name for s in screens}
        assert "BtnPrimary" not in names

    def test_captures_direct_component_refs(self):
        from design_graph.parsing.js_parser import find_all_boundaries
        bounds = find_all_boundaries(SCREENS_JS)
        screens = extract_screens(SCREENS_JS, bounds)
        rest_page = next(s for s in screens if s.name == "RestaurantsPage")
        assert "SectionCard" in rest_page.component_refs
        assert "BtnPrimary" in rest_page.component_refs
        assert "ConfirmModal" in rest_page.component_refs

    def test_does_not_include_internals_as_refs(self):
        js = "function HomePage() { return (<React.Fragment><div/></React.Fragment>) }"
        from design_graph.parsing.js_parser import find_all_boundaries
        bounds = find_all_boundaries(js)
        screens = extract_screens(js, bounds)
        home = next((s for s in screens if s.name == "HomePage"), None)
        if home:
            assert "Fragment" not in home.component_refs
            assert "React" not in home.component_refs

    def test_screen_does_not_include_own_name_in_refs(self):
        from design_graph.parsing.js_parser import find_all_boundaries
        bounds = find_all_boundaries(SCREENS_JS)
        screens = extract_screens(SCREENS_JS, bounds)
        for screen in screens:
            assert screen.name not in screen.component_refs

    def test_component_refs_sorted(self):
        from design_graph.parsing.js_parser import find_all_boundaries
        bounds = find_all_boundaries(SCREENS_JS)
        screens = extract_screens(SCREENS_JS, bounds)
        for screen in screens:
            assert screen.component_refs == sorted(screen.component_refs)

    def test_empty_js_returns_empty(self):
        assert extract_screens("", []) == []

    def test_sections_count_initialized_to_zero(self):
        from design_graph.parsing.js_parser import find_all_boundaries
        bounds = find_all_boundaries(SCREENS_JS)
        screens = extract_screens(SCREENS_JS, bounds)
        for screen in screens:
            assert screen.sections_count == 0  # preenchido depois pelo SectionExtractor
```

---

## Done when

- [ ] Todos os testes passam
- [ ] `is_screen("RestaurantsPage")` → True; `is_screen("BtnPrimary")` → False
- [ ] Mesmo resultado que `extract_screen_map()` do legado para `simple.html`
      (verificado no test de paridade T06)
