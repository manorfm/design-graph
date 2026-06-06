# Plan 05 — Fase 6: Chunker

## Objetivo

Implementar o chunker de HTML para contexto de IA. Deve funcionar tanto
integrado ao pipeline completo quanto standalone (`design-graph chunk`).
Suporte a React bundled e plain HTML.

## Pré-requisito

Fase 2 completa: `ExtractedScreen`, `ExtractedSection`, `ExtractedComponent`.
`html_parser.py` com `extract_dom_patterns` e `extract_semantic_sections`.

## Entregáveis

```
src/design_graph/extraction/chunker.py
src/design_graph/cli/build.py  (cmd_chunk adicionado)
tests/unit/extraction/test_chunker.py
tests/fixtures/plain.html       (nova fixture)
tests/fixtures/large_bundle.html (nova fixture)
```

## Fixtures necessárias

### `plain.html`

HTML puro sem React. Deve ter:
- `<nav>` com links
- `<main>` com `<section>` aninhadas
- Pelo menos 4 instâncias de um padrão "card" (div > img + h3 + p + button)
- `<footer>`

### `large_bundle.html`

HTML com bundle React simulando 50+ componentes para testar:
- Single-pass não explode com muitos componentes
- Chunking gera granularidade correta
- Sem duplicatas nos chunks

## Sequência TDD

```python
# tests/unit/extraction/test_chunker.py

class TestChunkId:
    def test_snake_case_conversion(self):
        assert _to_chunk_id("RestaurantsPage") == "restaurants_page"

    def test_double_underscore_for_section(self):
        assert _to_chunk_id("RestaurantsPage__Header") == "restaurants_page__header"

    def test_no_special_chars(self):
        cid = _to_chunk_id("Tela com Espaços!")
        assert re.match(r'^[a-z0-9_]+$', cid)


class TestChunkExtractedData:
    SCREEN = ExtractedScreen(name="RestaurantsPage", component_refs=["SectionCard", "BtnPrimary"], sections_count=0)
    SECTION_SMALL = ExtractedSection(name="Header", jsx_snippet="<div>header pequeno</div>", ...)
    SECTION_LARGE = ExtractedSection(name="Lista", jsx_snippet="X" * 15_000, ...)  # > max_chars

    def test_screen_without_sections_generates_one_chunk(self):
        chunks = chunk_extracted_data([self.SCREEN], {}, {}, max_chars=12_000)
        screen_chunks = [c for c in chunks if c.level == "screen"]
        assert len(screen_chunks) == 1

    def test_small_section_generates_one_chunk(self):
        chunks = chunk_extracted_data(
            [self.SCREEN],
            {"RestaurantsPage": [self.SECTION_SMALL]},
            {},
            max_chars=12_000,
        )
        section_chunks = [c for c in chunks if c.level == "section"]
        assert len(section_chunks) == 1
        assert section_chunks[0].breadcrumb == "RestaurantsPage > Header"

    def test_large_section_splits_by_component(self):
        # Seção com jsx_snippet grande → gera chunks por componente
        comp = ExtractedComponent(name="SectionCard", jsx_snippet="<div>card</div>", ...)
        chunks = chunk_extracted_data(
            [self.SCREEN],
            {"RestaurantsPage": [self.SECTION_LARGE]},
            {"SectionCard": comp},
            max_chars=12_000,
        )
        comp_chunks = [c for c in chunks if c.level == "component"]
        assert len(comp_chunks) >= 1

    def test_chunk_id_is_unique(self):
        chunks = chunk_extracted_data([self.SCREEN], ..., ...)
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids))

    def test_no_empty_content_chunks(self):
        chunks = chunk_extracted_data([self.SCREEN], ..., ...)
        assert all(c.content for c in chunks)

    def test_parent_id_links_section_to_screen(self):
        chunks = chunk_extracted_data(
            [self.SCREEN],
            {"RestaurantsPage": [self.SECTION_SMALL]},
            {},
        )
        section_chunk = next(c for c in chunks if c.level == "section")
        assert section_chunk.parent_id == "restaurants_page"

    def test_sibling_ids_populated(self):
        sec2 = ExtractedSection(name="Filtros", jsx_snippet="<div>filtros</div>", ...)
        chunks = chunk_extracted_data(
            [self.SCREEN],
            {"RestaurantsPage": [self.SECTION_SMALL, sec2]},
            {},
        )
        header_chunk = next(c for c in chunks if "header" in c.chunk_id)
        assert "restaurants_page__filtros" in header_chunk.sibling_ids

    def test_tokens_est_within_limit(self):
        chunks = chunk_extracted_data([self.SCREEN], ..., ..., max_chars=12_000)
        assert all(c.tokens_est <= 12_000 // 4 for c in chunks)


class TestChunkPlainHtml:
    def test_plain_html_semantic_sections(self):
        # plain.html tem nav, main, footer → 3+ chunks
        from tests.fixtures import PLAIN_HTML_PATH
        sources = asyncio.run(load(PLAIN_HTML_PATH))
        dom_patterns = extract_dom_patterns(BeautifulSoup(sources.inner_html, "html.parser"))
        semantic = extract_semantic_sections(BeautifulSoup(sources.inner_html, "html.parser"))
        assert len(semantic) >= 3

    def test_repeated_dom_pattern_detected(self):
        # plain.html tem 4 instâncias de "card" → detectado como componente
        from tests.fixtures import PLAIN_HTML_PATH
        sources = asyncio.run(load(PLAIN_HTML_PATH))
        soup = BeautifulSoup(sources.inner_html, "html.parser")
        patterns = extract_dom_patterns(soup, min_count=3)
        assert len(patterns) >= 1


class TestExportChunksJsonl:
    def test_creates_valid_jsonl(self, tmp_path):
        chunks = [make_chunk("id_1"), make_chunk("id_2")]
        output = tmp_path / "chunks.jsonl"
        export_chunks_jsonl(chunks, output)
        lines = output.read_text().splitlines()
        assert len(lines) == 2
        for line in lines:
            data = json.loads(line)
            assert "chunk_id" in data
            assert "breadcrumb" in data
            assert "content" in data
```

## Critério de aceite

```bash
pytest tests/unit/extraction/test_chunker.py -v
design-graph chunk tests/fixtures/simple.html --output /tmp/chunks.jsonl
# Verificar que chunks.jsonl tem linhas válidas, breadcrumbs fazem sentido,
# nenhum chunk tem content vazio
```

## Guardrails desta fase

1. `chunker.py` não abre nenhum arquivo — recebe entidades já extraídas
2. `chunk_id` sempre satisfaz `re.match(r'^[a-z0-9_]+$', chunk_id)`
3. `export_chunks_jsonl` não modifica a lista de chunks
4. O cmd_chunk da CLI não requer banco Kuzu — funciona com só parsing + extraction
