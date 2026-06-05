# T01 — SourceLoader

**Fase**: 1 — Parsing
**Arquivo**: `src/design_graph/parsing/source_loader.py`
**Depende de**: `core/models.py` (RawSources), `parsing/format_detector.py`
**Bloqueia**: T06 (ComponentExtractor), T09 (GraphSchema)

---

## Contrato

```python
@dataclass(frozen=True)
class RawSources:
    js: str
    css: str
    inner_html: str
    html_hash: str
    format: str  # "bundled_react" | "tailwind" | "plain_html"

async def load(html_path: Path) -> RawSources:
    """Lê arquivo HTML e retorna fontes estruturadas. I/O async via to_thread."""
```

---

## TDD — escreva estes testes ANTES de implementar

```python
# tests/unit/parsing/test_source_loader.py

class TestLoad:
    def test_returns_raw_sources(self, simple_html_path):
        sources = asyncio.run(load(simple_html_path))
        assert isinstance(sources, RawSources)

    def test_hash_is_deterministic(self, simple_html_path):
        a = asyncio.run(load(simple_html_path))
        b = asyncio.run(load(simple_html_path))
        assert a.html_hash == b.html_hash

    def test_hash_changes_with_content(self, tmp_path):
        f1 = tmp_path / "a.html"; f1.write_text("<html>v1</html>")
        f2 = tmp_path / "b.html"; f2.write_text("<html>v2</html>")
        assert asyncio.run(load(f1)).html_hash != asyncio.run(load(f2)).html_hash

    def test_js_is_string(self, simple_html_path):
        sources = asyncio.run(load(simple_html_path))
        assert isinstance(sources.js, str)

    def test_js_never_none(self, simple_html_path):
        sources = asyncio.run(load(simple_html_path))
        assert sources.js is not None

    def test_bundled_react_extracts_js(self, bundled_html_path):
        sources = asyncio.run(load(bundled_html_path))
        assert len(sources.js) > 1000
        assert sources.format == "bundled_react"

    def test_plain_html_extracts_script_tags(self, plain_html_path):
        sources = asyncio.run(load(plain_html_path))
        assert sources.format == "plain_html"

    def test_malformed_bundle_json_does_not_raise(self, tmp_path):
        # Script tag com JSON malformado → não lança, retorna js=""
        f = tmp_path / "bad.html"
        f.write_text('<html><script>{"broken": json}</script></html>')
        sources = asyncio.run(load(f))
        assert isinstance(sources.js, str)  # não explode
```

---

## Implementação

### Responsabilidades deste arquivo

1. Ler bytes do arquivo (async)
2. Computar `html_hash`
3. Detectar formato (delega para `format_detector`)
4. Extrair JS/CSS de acordo com o formato (estratégia interna)
5. Retornar `RawSources` imutável

### Responsabilidades que NÃO são deste arquivo

- Interpretar o JS (→ `js_parser.py`)
- Extrair tokens (→ `token_extractor.py`)
- Detectar componentes (→ `extraction/`)

### Estratégias internas (privadas)

```python
def _extract_bundled_react(soup: BeautifulSoup) -> tuple[str, str, str]:
    """js, css, inner_html para bundled_react."""

def _extract_plain(html: str, soup: BeautifulSoup) -> tuple[str, str, str]:
    """js, css, inner_html para tailwind/plain_html."""
```

---

## Guardrails

- `RawSources` é `frozen=True` — nenhum código externo pode modificar após criação
- Se `html_path` não existir: lança `FileNotFoundError` (não silencia)
- Se script tag tem JSON malformado: loga no stderr, continua sem aquele script
- `inner_html` nunca é menor que 20 chars (se for, algo deu errado — logar aviso)

---

## Done when

- [ ] Todos os testes desta task passam
- [ ] `sources.js` para `tests/fixtures/simple.html` produz o mesmo conteúdo
      que `load_sources()` do legado `build_graph.py`
- [ ] Nenhum import de `extraction/`, `graph/`, ou `mcp/` neste arquivo
