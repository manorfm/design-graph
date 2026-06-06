# T06 — ComponentExtractor (Single-Pass)

**Fase**: 2 — Extraction
**Arquivo**: `src/design_graph/extraction/component_extractor.py`
**Depende de**: T01 (RawSources), T03 (FunctionBoundary, extract_return_block), T04 (DesignToken, build_token_map), `core/patterns.py`, `core/constants.py`
**Bloqueia**: T10 (GraphWriter), T13 (PipelineCoordinator)

---

## Por que single-pass

O legado percorre `js[fn_start : fn_start + 14000]` 5× por componente:
`extract_jsx_snippet`, `extract_styles`, `extract_interactions`, `extract_texts`
e a busca de `classes`. Para 100 componentes, isso é 500 varreduras.

O single-pass percorre `js[boundary.start : boundary.end]` exatamente **1×**
por componente, coletando tudo. Com `FunctionBoundary.end` real (não fixo),
componentes grandes também são cobertos corretamente.

---

## Contrato

```python
@dataclass
class ExtractedComponent:
    name: str
    comp_type: str
    jsx_snippet: str
    occurrence: int
    classes: str
    styles: list[StyleEntry]
    interactions: list[InteractionEntry]
    texts: list[TextEntry]
    child_refs: list[str]   # componentes referenciados no JSX deste componente

def extract_component(
    js: str,
    boundary: FunctionBoundary,
    occurrence: int,
    token_map: dict[str, list[DesignToken]],
) -> ExtractedComponent:
    """
    Extrai todos os dados do componente em uma única varredura do seu corpo.
    Pura: não modifica js nem token_map.
    """

async def extract_all_components(
    js: str,
    boundaries: list[FunctionBoundary],
    occurrences: Counter,
    token_map: dict,
    concurrency: int = 8,
) -> list[ExtractedComponent]:
    """
    Extrai todos os componentes de forma concorrente usando asyncio.to_thread.
    Retorna lista ordenada por occurrence desc.
    """
```

---

## TDD

```python
# tests/unit/extraction/test_component_extractor.py

BTN_JS = """
function BtnPrimary() {
    return (
        <button
            className="btn-primary action-btn"
            style={{backgroundColor: '#ffb81c', padding: '8px', transition: 'all 0.2s'}}
            onMouseEnter={e => e.target.style.backgroundColor = '#f59e0b'}
            onMouseLeave={e => e.target.style.backgroundColor = '#ffb81c'}
        >
            Confirmar
        </button>
    )
}
"""

def _make_boundary(js: str, name: str) -> FunctionBoundary:
    from design_graph.parsing.js_parser import find_function_boundaries
    from design_graph.core.patterns import RE_COMP_FN
    bounds = find_function_boundaries(js, RE_COMP_FN)
    return next(b for b in bounds if b.name == name)


class TestExtractComponent:
    def test_name_matches_boundary(self):
        b = _make_boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, {})
        assert comp.name == "BtnPrimary"

    def test_comp_type_inferred(self):
        b = _make_boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, {})
        assert comp.comp_type == "button"

    def test_jsx_snippet_extracted(self):
        b = _make_boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, {})
        assert "button" in comp.jsx_snippet.lower()

    def test_default_style_found(self):
        b = _make_boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, {})
        props = {s.property for s in comp.styles if s.state == "default"}
        assert "backgroundColor" in props or "background" in props.lower()

    def test_hover_interaction_found(self):
        b = _make_boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, {})
        assert any(i.trigger == "hover" for i in comp.interactions)

    def test_button_text_found(self):
        b = _make_boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, {})
        assert any("Confirmar" in t.content for t in comp.texts)

    def test_classes_extracted(self):
        b = _make_boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, {})
        assert "btn-primary" in comp.classes or "action-btn" in comp.classes

    def test_child_refs_captured(self):
        js = """
        function RestCard() {
            return (
                <div>
                    <Badge status="open" />
                    <StarRating value={4} />
                </div>
            )
        }
        """
        b = _make_boundary(js, "RestCard")
        comp = extract_component(js, b, 1, {})
        assert "Badge" in comp.child_refs
        assert "StarRating" in comp.child_refs

    def test_self_not_in_child_refs(self):
        js = "function SelfRef() { return (<div className='SelfRef' />) }"
        b = _make_boundary(js, "SelfRef")
        comp = extract_component(js, b, 1, {})
        assert "SelfRef" not in comp.child_refs

    def test_internals_not_in_child_refs(self):
        js = "function Foo() { return (<React.Fragment><div/></React.Fragment>) }"
        b = _make_boundary(js, "Foo")
        comp = extract_component(js, b, 1, {})
        assert "Fragment" not in comp.child_refs
        assert "React" not in comp.child_refs

    def test_token_map_links_styles_to_tokens(self):
        token = DesignToken(id="col_1", category="color",
                            label="primary", value="#ffb81c", usage=5)
        token_map = build_token_map([token])
        b = _make_boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, token_map)
        # O token_map é usado pelo writer, mas o comp não armazena tokens diretamente
        # Este teste verifica que nenhuma exceção ocorre com token_map preenchido
        assert comp is not None

    def test_occurrence_stored(self):
        b = _make_boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 42, {})
        assert comp.occurrence == 42

    def test_styles_limited_to_40(self):
        # Componente com muitas propriedades inline
        many_styles = " ".join(f"style={{{{prop{i}: 'val{i}'}}}}" for i in range(60))
        js = f"function BigComp() {{ return (<div>{many_styles}</div>) }}"
        b = _make_boundary(js, "BigComp")
        comp = extract_component(js, b, 1, {})
        assert len(comp.styles) <= 40

    def test_texts_limited_to_30(self):
        many_texts = " ".join(f'"Text número {i}"' for i in range(40))
        js = f"function TextHeavy() {{ return (<div>{many_texts}</div>) }}"
        b = _make_boundary(js, "TextHeavy")
        comp = extract_component(js, b, 1, {})
        assert len(comp.texts) <= 30


class TestExtractAllComponents:
    def test_extracts_multiple_components(self):
        js = BTN_JS + """
        function SectionCard() {
            return (<div className="card"><h3>Title</h3></div>)
        }
        """
        from design_graph.parsing.js_parser import find_all_boundaries
        bounds = find_all_boundaries(js)
        occ = Counter(b.name for b in bounds)
        comps = asyncio.run(extract_all_components(js, bounds, occ, {}))
        names = {c.name for c in comps}
        assert "BtnPrimary" in names
        assert "SectionCard" in names

    def test_concurrency_does_not_produce_duplicates(self):
        # 20 componentes únicos — nenhum deve aparecer duas vezes
        funcs = "\n".join(
            f"function Comp{i}() {{ return (<div>comp{i}</div>) }}"
            for i in range(20)
        )
        from design_graph.parsing.js_parser import find_all_boundaries
        bounds = find_all_boundaries(funcs)
        occ = Counter(b.name for b in bounds)
        comps = asyncio.run(extract_all_components(funcs, bounds, occ, {}))
        names = [c.name for c in comps]
        assert len(names) == len(set(names))

    def test_semaphore_respected(self):
        # Não deve lançar exceção mesmo com concurrency=1
        js = BTN_JS
        from design_graph.parsing.js_parser import find_all_boundaries
        bounds = find_all_boundaries(js)
        occ = Counter(b.name for b in bounds)
        comps = asyncio.run(extract_all_components(js, bounds, occ, {}, concurrency=1))
        assert len(comps) >= 1
```

---

## Guardrails

1. `js` nunca é modificado — é passado apenas por referência (string imutável)
2. `token_map` nunca é modificado dentro de `extract_component`
3. `child_refs` não contém strings vazias nem o próprio `boundary.name`
4. A varredura da window acontece exatamente 1× por `extract_component`
   (verificável por mock de `re.finditer` em teste específico se necessário)

---

## Done when

- [x] Todos os testes acima passam
- [x] `extract_component(BTN_JS, boundary, 1, {})` produz os mesmos `styles` e
      `interactions` que o legado `extract_styles(BTN_JS, "BtnPrimary")` e
      `extract_interactions(BTN_JS, "BtnPrimary")` — verificado no test de paridade
- [x] `extract_all_components` com 50 componentes conclui em < 3s (performance check)
