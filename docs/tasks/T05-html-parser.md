# T05 — HTMLParser

**Fase**: 1 — Parsing
**Arquivo**: `src/design_graph/parsing/html_parser.py`
**Depende de**: `core/constants.py` (SEMANTIC_KEYWORDS)
**Bloqueia**: T08 (SectionExtractor — fallback semântico), T16 (Chunker)

---

## Contrato

```python
@dataclass(frozen=True)
class DOMPattern:
    signature: str          # "div.card>img,h3,p,button"
    count: int
    first_example: str      # HTML truncado a 600 chars
    inferred_name: str      # ex: "RestaurantCard"
    semantic_type: str      # "card" | "nav" | "list-item" | etc.

def extract_dom_patterns(
    soup: BeautifulSoup,
    min_count: int = 3,
) -> list[DOMPattern]:
    """
    Detecta estruturas DOM repetidas >= min_count vezes.
    Retorna ordenado por count desc.
    """

def extract_semantic_sections(soup: BeautifulSoup) -> list[dict]:
    """
    Usa tags HTML5 e headings como delimitadores de seção.
    Retorna: [{"name": str, "tag": str, "html": str, "depth": int}]
    """
```

---

## TDD

```python
# tests/unit/parsing/test_html_parser.py

PLAIN_HTML = """
<html><body>
  <nav class="navbar">
    <a href="/">Home</a>
    <a href="/menu">Menu</a>
  </nav>
  <main>
    <section id="restaurants">
      <h2>Restaurantes</h2>
      <div class="card"><img src="a.jpg"><h3>Rest A</h3><p>Desc A</p><button>Ver</button></div>
      <div class="card"><img src="b.jpg"><h3>Rest B</h3><p>Desc B</p><button>Ver</button></div>
      <div class="card"><img src="c.jpg"><h3>Rest C</h3><p>Desc C</p><button>Ver</button></div>
      <div class="card"><img src="d.jpg"><h3>Rest D</h3><p>Desc D</p><button>Ver</button></div>
    </section>
  </main>
  <footer><p>© 2024</p></footer>
</body></html>
"""

SOUP = BeautifulSoup(PLAIN_HTML, "html.parser")


class TestExtractDOMPatterns:
    def test_finds_repeated_card_pattern(self):
        patterns = extract_dom_patterns(SOUP, min_count=3)
        assert len(patterns) >= 1

    def test_count_reflects_repetitions(self):
        patterns = extract_dom_patterns(SOUP, min_count=3)
        card_pattern = next((p for p in patterns if "card" in p.signature.lower()), None)
        assert card_pattern is not None
        assert card_pattern.count >= 4

    def test_min_count_filter_works(self):
        # Padrão que aparece 2× não deve aparecer com min_count=3
        patterns_3 = extract_dom_patterns(SOUP, min_count=3)
        patterns_1 = extract_dom_patterns(SOUP, min_count=1)
        assert len(patterns_1) >= len(patterns_3)

    def test_first_example_is_valid_html(self):
        patterns = extract_dom_patterns(SOUP, min_count=3)
        for p in patterns:
            assert len(p.first_example) > 0
            assert len(p.first_example) <= 600

    def test_inferred_name_is_pascal_case(self):
        patterns = extract_dom_patterns(SOUP, min_count=3)
        for p in patterns:
            assert p.inferred_name[0].isupper()

    def test_signature_has_no_spaces(self):
        patterns = extract_dom_patterns(SOUP, min_count=3)
        for p in patterns:
            assert ' ' not in p.signature

    def test_simple_tags_excluded(self):
        # <span> puro não é componente
        html = "<span>A</span><span>B</span><span>C</span>"
        soup = BeautifulSoup(html, "html.parser")
        patterns = extract_dom_patterns(soup, min_count=3)
        assert all(len(p.signature) >= 15 for p in patterns)


class TestExtractSemanticSections:
    def test_finds_nav(self):
        sections = extract_semantic_sections(SOUP)
        names = [s["name"] for s in sections]
        assert any("nav" in n.lower() or "navigation" in n.lower() for n in names)

    def test_finds_main(self):
        sections = extract_semantic_sections(SOUP)
        tags = [s["tag"] for s in sections]
        assert "main" in tags or "section" in tags

    def test_finds_footer(self):
        sections = extract_semantic_sections(SOUP)
        tags = [s["tag"] for s in sections]
        assert "footer" in tags

    def test_headings_used_as_section_names(self):
        html = "<main><h2>Cardápio</h2><p>...</p></main>"
        soup = BeautifulSoup(html, "html.parser")
        sections = extract_semantic_sections(soup)
        assert any("Cardápio" in s.get("name", "") for s in sections)

    def test_each_section_has_html(self):
        sections = extract_semantic_sections(SOUP)
        for s in sections:
            assert "html" in s
            assert len(s["html"]) > 0

    def test_empty_soup_returns_empty_list(self):
        soup = BeautifulSoup("", "html.parser")
        assert extract_semantic_sections(soup) == []
```

---

## Implementação de `_structure_signature`

```python
def _structure_signature(tag, depth: int = 0, max_depth: int = 3) -> str:
    if depth >= max_depth:
        return tag.name
    children = [c for c in tag.children if hasattr(c, 'name') and c.name]
    classes = tag.get('class', [])
    cls_hint = f".{classes[0]}" if classes else ""
    base = f"{tag.name}{cls_hint}"
    if not children:
        return base
    child_sigs = ','.join(
        _structure_signature(c, depth + 1, max_depth) for c in children[:6]
    )
    return f"{base}>{child_sigs}"
```

## Inferência de nome em `extract_dom_patterns`

```python
_STRUCTURE_TO_NAME: list[tuple[list[str], str]] = [
    (["img", "h3", "p", "button"], "Card"),
    (["img", "h2", "p"],           "FeaturedCard"),
    (["input", "button"],          "SearchBar"),
    (["th", "tr"],                 "DataTable"),
    (["h1"],                       "PageHeader"),
    (["li"],                       "ListItem"),
]

def _infer_name_from_signature(sig: str) -> str:
    sig_lower = sig.lower()
    for keywords, name in _STRUCTURE_TO_NAME:
        if all(k in sig_lower for k in keywords):
            return name
    # Fallback: usar primeiro elemento do sig em PascalCase
    first_tag = sig.split(">")[0].split(".")[0]
    return first_tag.capitalize() + "Component"
```

---

## Done when

- [ ] Todos os testes passam com `plain.html` fixture
- [ ] `extract_dom_patterns` retorna pelo menos 1 padrão para `plain.html`
- [ ] `extract_semantic_sections` retorna pelo menos 3 seções para `plain.html`
- [ ] Nenhuma exceção ao processar HTML vazio ou malformado
