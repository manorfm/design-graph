# T16 — Chunker

**Fase**: 6 — Chunker
**Arquivo**: `src/design_graph/extraction/chunker.py`
**Depende de**: T06 (ExtractedComponent), T07 (ExtractedScreen), T08 (ExtractedSection), T05 (html_parser)
**Bloqueia**: CLI `design-graph chunk`

---

## Contrato

```python
@dataclass
class ChunkEnvelope:
    chunk_id: str
    breadcrumb: str
    level: str              # "screen" | "section" | "component"
    parent_id: str | None
    sibling_ids: list[str]
    child_ids: list[str]
    content: str
    tokens_est: int
    component_refs: list[str]
    context_summary: str
    source_screen: str

def chunk_extracted_data(
    screens: list[ExtractedScreen],
    sections: dict[str, list[ExtractedSection]],
    components: dict[str, ExtractedComponent],
    max_chars: int = 12_000,
) -> list[ChunkEnvelope]:
    """Gera chunks hierárquicos Screen > Section > Component."""

def export_chunks_jsonl(chunks: list[ChunkEnvelope], output_path: Path) -> None:
    """Escreve JSONL — um chunk por linha."""

def _to_chunk_id(name: str) -> str:
    """Converte qualquer string para snake_case seguro: [a-z0-9_]+."""
```

---

## TDD (ver Plan 05 para testes completos)

```python
# tests/unit/extraction/test_chunker.py

# Testes resumidos aqui — ver Plan 05 para versão completa

class TestToChunkId:
    def test_pascal_to_snake(self):
        assert _to_chunk_id("RestaurantsPage") == "restaurants_page"

    def test_double_underscore_separator(self):
        assert "__" in _to_chunk_id("Page__Section")

    def test_only_valid_chars(self):
        cid = _to_chunk_id("Tela com Acentuação!")
        assert re.match(r'^[a-z0-9_]+$', cid)


class TestChunkExtractedData:
    def test_no_empty_content_chunks(self): ...
    def test_unique_chunk_ids(self): ...
    def test_parent_id_links_section_to_screen(self): ...
    def test_sibling_ids_populated(self): ...
    def test_tokens_est_within_limit(self): ...
    def test_large_section_splits_by_component(self): ...


class TestExportChunksJsonl:
    def test_creates_valid_jsonl(self, tmp_path):
        chunks = [
            ChunkEnvelope(
                chunk_id="pg", breadcrumb="Pg", level="screen",
                parent_id=None, sibling_ids=[], child_ids=[],
                content="<div>test</div>", tokens_est=10,
                component_refs=[], context_summary="Test", source_screen="Pg"
            )
        ]
        output = tmp_path / "out.jsonl"
        export_chunks_jsonl(chunks, output)
        lines = output.read_text().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["chunk_id"] == "pg"
        assert data["breadcrumb"] == "Pg"

    def test_each_line_valid_json(self, tmp_path):
        chunks = [_make_chunk(f"id_{i}") for i in range(5)]
        output = tmp_path / "out.jsonl"
        export_chunks_jsonl(chunks, output)
        for line in output.read_text().splitlines():
            json.loads(line)  # não deve lançar

    def test_empty_chunks_creates_empty_file(self, tmp_path):
        output = tmp_path / "out.jsonl"
        export_chunks_jsonl([], output)
        assert output.read_text() == ""
```

---

## Fixtures novas necessárias

### `tests/fixtures/plain.html`

```html
<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="UTF-8"><title>Plain Test</title></head>
<body>
  <nav class="navbar">
    <a href="/">Home</a>
    <a href="/menu">Cardápio</a>
    <a href="/about">Sobre</a>
  </nav>
  <main>
    <section id="restaurants">
      <h2>Restaurantes em Destaque</h2>
      <div class="card">
        <img src="r1.jpg" alt="Rest A">
        <h3>Restaurante A</h3>
        <p>Culinária italiana, centro</p>
        <button class="btn-primary">Ver Menu</button>
      </div>
      <div class="card">
        <img src="r2.jpg" alt="Rest B">
        <h3>Restaurante B</h3>
        <p>Culinária japonesa, sul</p>
        <button class="btn-primary">Ver Menu</button>
      </div>
      <div class="card">
        <img src="r3.jpg" alt="Rest C">
        <h3>Restaurante C</h3>
        <p>Culinária brasileira, norte</p>
        <button class="btn-primary">Ver Menu</button>
      </div>
      <div class="card">
        <img src="r4.jpg" alt="Rest D">
        <h3>Restaurante D</h3>
        <p>Culinária mexicana, leste</p>
        <button class="btn-primary">Ver Menu</button>
      </div>
    </section>
  </main>
  <footer>
    <p>&copy; 2024 iPede. Todos os direitos reservados.</p>
  </footer>
</body>
</html>
```

### `tests/fixtures/large_bundle.html`

Script que gera um HTML com 50 componentes React simulados (para stress test).
Criado como arquivo Python em `tests/fixtures/generate_large_bundle.py`.

---

## CLI command `design-graph chunk`

```python
# src/design_graph/cli/build.py — adicionar ao parser

def cmd_chunk(args):
    """
    Extrai chunks de um arquivo HTML sem construir o grafo completo.
    Útil para processar HTML gigante gerado por agente.
    """
    import asyncio
    from design_graph.parsing.source_loader import load
    from design_graph.parsing.js_parser import find_all_boundaries
    from design_graph.extraction.component_extractor import extract_all_components
    from design_graph.extraction.screen_extractor import extract_screens
    from design_graph.extraction.section_extractor import extract_sections
    from design_graph.extraction.chunker import chunk_extracted_data, export_chunks_jsonl
    from design_graph.parsing.token_extractor import extract_tokens, build_token_map
    from collections import Counter
    import asyncio

    async def _run():
        sources = await load(Path(args.html))
        bounds = find_all_boundaries(sources.js)
        tokens = extract_tokens(sources)
        token_map = build_token_map(tokens)
        occ = Counter(b.name for b in bounds)
        comps_list = await extract_all_components(sources.js, bounds, occ, token_map)
        comps_dict = {c.name: c for c in comps_list}
        screens = extract_screens(sources.js, bounds)
        secs_map = {}
        from design_graph.parsing.js_parser import find_function_boundaries
        from design_graph.core.patterns import RE_SCREEN_NAME
        screen_bounds = {b.name: b for b in find_function_boundaries(sources.js, RE_SCREEN_NAME)}
        for screen in screens:
            b = screen_bounds.get(screen.name)
            if b:
                secs_map[screen.name] = extract_sections(sources.js, screen, b)
        chunks = chunk_extracted_data(screens, secs_map, comps_dict, args.max_chars)
        output = Path(args.output) if args.output else Path(args.html).with_suffix(".jsonl")
        export_chunks_jsonl(chunks, output)
        print(f"{len(chunks)} chunks → {output}")

    asyncio.run(_run())
```

**Uso:**
```bash
design-graph chunk prototype.html
design-graph chunk prototype.html --output chunks.jsonl --max-chars 8000
```

---

## Done when

- [x] Todos os testes de T16 passam
- [x] `design-graph chunk tests/fixtures/simple.html` gera arquivo JSONL válido
- [x] `design-graph chunk tests/fixtures/plain.html` detecta seções semânticas
- [x] Nenhum chunk tem `content` vazio
- [x] `_to_chunk_id` satisfaz `re.match(r'^[a-z0-9_]+$', id)` para qualquer input
