# T02 — FormatDetector

**Fase**: 1 — Parsing
**Arquivo**: `src/design_graph/parsing/format_detector.py`
**Depende de**: nada (função pura)
**Bloqueia**: T01 (SourceLoader)

---

## Contrato

```python
def detect(html: str, soup: BeautifulSoup) -> str:
    """
    Detecta o formato do protótipo HTML.
    Retorna: "bundled_react" | "tailwind" | "plain_html"
    Nunca lança exceção. Em caso de dúvida, retorna "plain_html".
    """
```

---

## TDD

```python
# tests/unit/parsing/test_format_detector.py

class TestDetect:
    def test_bundled_react_by_compressed_flag(self):
        html = '<script>{"compressed": true, "data": "abc"}</script>'
        soup = BeautifulSoup(html, "html.parser")
        assert detect(html, soup) == "bundled_react"

    def test_bundled_react_by_create_element(self):
        # Script grande com createElement
        js = "createElement" + "x" * 100_000
        html = f"<script>{js}</script>"
        soup = BeautifulSoup(html, "html.parser")
        assert detect(html, soup) == "bundled_react"

    def test_tailwind_detection(self):
        html = "<style>.flex { display: flex } .p-4 { padding: 1rem }</style>"
        soup = BeautifulSoup(html, "html.parser")
        assert detect(html, soup) == "tailwind"

    def test_plain_html_default(self):
        html = "<html><body><p>Hello</p></body></html>"
        soup = BeautifulSoup(html, "html.parser")
        assert detect(html, soup) == "plain_html"

    def test_empty_html_returns_plain(self):
        assert detect("", BeautifulSoup("", "html.parser")) == "plain_html"

    def test_returns_only_valid_values(self):
        valid = {"bundled_react", "tailwind", "plain_html"}
        test_cases = ["", "<div/>", "<script>big" + "x" * 200_000 + "</script>"]
        for html in test_cases:
            soup = BeautifulSoup(html, "html.parser")
            assert detect(html, soup) in valid
```

---

## Implementação

```python
BUNDLED_REACT_THRESHOLD_BYTES = 50_000
BUNDLED_REACT_THRESHOLD_LARGE = 100_000

def detect(html: str, soup: BeautifulSoup) -> str:
    for script in soup.find_all("script"):
        text = script.get_text()
        if len(text) > BUNDLED_REACT_THRESHOLD_BYTES and '"compressed": true' in text:
            return "bundled_react"
        if len(text) > BUNDLED_REACT_THRESHOLD_LARGE and "createElement" in text:
            return "bundled_react"

    style_text = " ".join(t.get_text() for t in soup.find_all("style"))
    if re.search(r'\.(flex|grid|p-\d|m-\d|text-|bg-|border-)\s*\{', style_text):
        return "tailwind"

    return "plain_html"
```

---

## Done when

- [x] Todos os testes passam
- [x] Nenhum `try/except` suprime exceções reais (só exceções de parsing de HTML)
- [x] As constantes de threshold ficam no topo do arquivo, não inline
