# T08 — SectionExtractor

**Fase**: 2 — Extraction
**Arquivo**: `src/design_graph/extraction/section_extractor.py`
**Depende de**: T03 (FunctionBoundary), T07 (ExtractedScreen), `core/patterns.py`
**Bloqueia**: T10 (GraphWriter), T13 (PipelineCoordinator)

---

## Contrato

```python
@dataclass
class ExtractedSection:
    id: str
    screen: str
    name: str
    styles: dict[str, str]
    component_refs: list[str]
    texts: list[str]
    jsx_snippet: str
    detection_method: str   # "comment" | "structural" | "semantic" | "none"

def extract_sections(
    js: str,
    screen: ExtractedScreen,
    boundary: FunctionBoundary,
) -> list[ExtractedSection]:
    """
    Tenta detectar seções em ordem de confiabilidade.
    Retorna lista vazia se nenhum método produzir seções de qualidade.
    """
```

---

## Estratégias em cascata

```
1. _detect_by_comment(js, boundary)
   → busca {/* ── Nome ── */} no return() da tela

2. _detect_by_structure(js, boundary)
   → busca divs com padding >= 16px como separadores

3. _detect_by_semantics(boundary)
   → usa html_parser.extract_semantic_sections() no inner_html
   (só ativo se format == "plain_html")
```

A primeira estratégia que produzir pelo menos 2 seções de qualidade vence.
Se nenhuma produzir, retorna `[]`.

---

## Critério de qualidade de seção

Uma seção é aceita se tiver **pelo menos uma** das condições:
- `len(component_refs) >= 1`
- `len(texts) >= 2`
- `len(styles) >= 3`

---

## TDD

```python
# tests/unit/extraction/test_section_extractor.py

WITH_COMMENTS_JS = """
function RestaurantsPage() {
    return (
        <div>
            {/* ── Header ── */}
            <h1>Restaurantes</h1>
            <BtnFilter />

            {/* ── Lista ── */}
            <SectionCard item={a} />
            <SectionCard item={b} />

            {/* ── Footer ── */}
            <p>© 2024</p>
        </div>
    )
}
"""

WITHOUT_COMMENTS_JS = """
function RestaurantsPage() {
    return (
        <div>
            <div style={{padding: '24px', marginBottom: '16px'}}>
                <h1>Restaurantes</h1>
                <BtnFilter />
            </div>
            <div style={{padding: '16px'}}>
                <SectionCard item={a} />
                <SectionCard item={b} />
            </div>
        </div>
    )
}
"""


class TestDetectByComment:
    def _sections(self, js):
        from design_graph.parsing.js_parser import find_all_boundaries
        from design_graph.core.patterns import RE_SCREEN_NAME
        bounds = find_all_boundaries(js)
        screen_b = next(b for b in bounds if b.name == "RestaurantsPage")
        screen = ExtractedScreen(name="RestaurantsPage", component_refs=[], sections_count=0)
        return extract_sections(js, screen, screen_b)

    def test_finds_three_sections(self):
        sections = self._sections(WITH_COMMENTS_JS)
        names = {s.name for s in sections}
        assert "Header" in names or "header" in [n.lower() for n in names]
        assert "Lista" in names or "lista" in [n.lower() for n in names]

    def test_detection_method_is_comment(self):
        sections = self._sections(WITH_COMMENTS_JS)
        assert all(s.detection_method == "comment" for s in sections)

    def test_components_attributed_to_correct_section(self):
        sections = self._sections(WITH_COMMENTS_JS)
        lista = next((s for s in sections if "lista" in s.name.lower()), None)
        assert lista is not None
        assert "SectionCard" in lista.component_refs

    def test_header_has_filter_button(self):
        sections = self._sections(WITH_COMMENTS_JS)
        header = next((s for s in sections if "header" in s.name.lower()), None)
        assert header is not None
        assert "BtnFilter" in header.component_refs


class TestDetectByStructure:
    def _sections(self, js):
        from design_graph.parsing.js_parser import find_all_boundaries
        bounds = find_all_boundaries(js)
        screen_b = next(b for b in bounds if b.name == "RestaurantsPage")
        screen = ExtractedScreen(name="RestaurantsPage", component_refs=[], sections_count=0)
        return extract_sections(js, screen, screen_b)

    def test_fallback_triggers_without_comments(self):
        sections = self._sections(WITHOUT_COMMENTS_JS)
        assert len(sections) >= 1

    def test_detection_method_is_structural(self):
        sections = self._sections(WITHOUT_COMMENTS_JS)
        assert any(s.detection_method == "structural" for s in sections)

    def test_max_8_sections_from_fallback(self):
        # Evitar fragmentação excessiva
        js = "\n".join(
            f"<div style={{{{padding:'20px'}}}}>block{i}<Comp{i}/></div>"
            for i in range(20)
        )
        full_js = f"function BigPage() {{ return (<div>{js}</div>) }}"
        from design_graph.parsing.js_parser import find_all_boundaries
        bounds = find_all_boundaries(full_js)
        screen_b = next(b for b in bounds if b.name == "BigPage")
        screen = ExtractedScreen(name="BigPage", component_refs=[], sections_count=0)
        sections = extract_sections(full_js, screen, screen_b)
        assert len(sections) <= 8


class TestQualityFilter:
    def test_empty_section_not_created(self):
        # Comentário sem nenhum componente nem texto → não vira seção
        js = """
        function EmptyPage() {
            return (
                <div>
                    {/* ── Empty ── */}
                </div>
            )
        }
        """
        from design_graph.parsing.js_parser import find_all_boundaries
        bounds = find_all_boundaries(js)
        screen_b = next(b for b in bounds if b.name == "EmptyPage")
        screen = ExtractedScreen(name="EmptyPage", component_refs=[], sections_count=0)
        sections = extract_sections(js, screen, screen_b)
        assert all(
            len(s.component_refs) >= 1 or len(s.texts) >= 2 or len(s.styles) >= 3
            for s in sections
        )

    def test_section_id_is_unique_per_screen(self):
        from design_graph.parsing.js_parser import find_all_boundaries
        bounds = find_all_boundaries(WITH_COMMENTS_JS)
        screen_b = next(b for b in bounds if b.name == "RestaurantsPage")
        screen = ExtractedScreen(name="RestaurantsPage", component_refs=[], sections_count=0)
        sections = extract_sections(WITH_COMMENTS_JS, screen, screen_b)
        ids = [s.id for s in sections]
        assert len(ids) == len(set(ids))
```

---

## Done when

- [ ] Todos os testes passam
- [ ] `WITH_COMMENTS_JS` → `detection_method == "comment"` para todas as seções
- [ ] `WITHOUT_COMMENTS_JS` → pelo menos 1 seção com `detection_method == "structural"`
- [ ] Seção sem componentes nem textos não é criada
