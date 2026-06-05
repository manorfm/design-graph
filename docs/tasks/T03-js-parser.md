# T03 — JSParser

**Fase**: 1 — Parsing
**Arquivo**: `src/design_graph/parsing/js_parser.py`
**Depende de**: `core/patterns.py`, `core/constants.py`
**Bloqueia**: T06 (ComponentExtractor), T07 (ScreenExtractor)

---

## Contrato

```python
@dataclass(frozen=True)
class FunctionBoundary:
    name: str
    start: int       # índice do "function NomeFn(" no JS
    body_start: int  # índice do corpo (logo após o "{" inicial)
    end: int         # índice após o "}" de fechamento

def find_function_end(js: str, fn_start: int) -> int:
    """Conta chaves para achar o fim real da função. Limite: fn_start + 120_000."""

def extract_return_block(js: str, fn_start: int, fn_end: int) -> str:
    """Extrai o conteúdo do return() contando parênteses. Retorna "" se não encontrar."""

def find_function_boundaries(js: str, name_pattern: re.Pattern) -> list[FunctionBoundary]:
    """Retorna FunctionBoundary para cada match do pattern, com end real."""

def find_all_boundaries(js: str) -> list[FunctionBoundary]:
    """Todas as funções PascalCase (RE_COMP_FN). Usa find_function_boundaries."""
```

---

## TDD

```python
# tests/unit/parsing/test_js_parser.py

class TestFindFunctionEnd:
    def test_simple_function(self):
        js = "function Foo() { return 1; } rest"
        end = find_function_end(js, 0)
        assert js[end - 1] == "}"
        assert "rest" in js[end:]   # nada depois do "}" foi consumido

    def test_nested_braces_not_premature(self):
        js = "function Foo() { const x = {a: {b: 1}}; return x; } after"
        end = find_function_end(js, 0)
        assert "after" in js[end:]

    def test_object_literal_in_return(self):
        js = "function Btn() { return (<div style={{color:'red'}} />); } next"
        end = find_function_end(js, 0)
        assert "next" in js[end:]

    def test_fallback_at_limit(self):
        # Função sem fechamento (JS truncado)
        js = "function Broken() { " + "x" * 200_000
        end = find_function_end(js, 0)
        assert end <= len(js)   # não explode

    def test_result_never_before_start(self):
        js = "function A() {} function B() {}"
        end = find_function_end(js, 0)
        assert end > 0


class TestExtractReturnBlock:
    def test_simple_return(self):
        js = "function Foo() { return (<div>hello</div>); }"
        result = extract_return_block(js, 0, len(js))
        assert "<div>hello</div>" in result

    def test_multiline_return(self):
        js = """function Foo() {
            return (
                <div>
                    <span>text</span>
                </div>
            );
        }"""
        result = extract_return_block(js, 0, len(js))
        assert "<span>text</span>" in result

    def test_no_return_gives_empty_string(self):
        js = "function Foo() { const x = 1; }"
        result = extract_return_block(js, 0, len(js))
        assert result == ""

    def test_nested_parens_handled(self):
        js = "function Foo() { return (fn(a, (b + c))); }"
        result = extract_return_block(js, 0, len(js))
        assert result != ""   # não fecha no primeiro ")"

    def test_never_returns_none(self):
        js = "function Foo() {}"
        assert extract_return_block(js, 0, len(js)) is not None


class TestFindFunctionBoundaries:
    JS = """
    function BtnPrimary() { return <div/>; }
    function SectionCard() { return <div/>; }
    function useState() { return null; }
    """

    def test_finds_matching_functions(self):
        from design_graph.core.patterns import RE_COMP_FN
        bounds = find_function_boundaries(self.JS, RE_COMP_FN)
        names = {b.name for b in bounds}
        assert "BtnPrimary" in names
        assert "SectionCard" in names

    def test_end_is_after_start(self):
        from design_graph.core.patterns import RE_COMP_FN
        bounds = find_function_boundaries(self.JS, RE_COMP_FN)
        for b in bounds:
            assert b.end > b.start

    def test_boundaries_do_not_overlap(self):
        from design_graph.core.patterns import RE_COMP_FN
        bounds = sorted(find_function_boundaries(self.JS, RE_COMP_FN), key=lambda b: b.start)
        for i in range(len(bounds) - 1):
            assert bounds[i].end <= bounds[i + 1].start
```

### Teste crítico: sem overlap de janelas

Este teste é o guardrail de concorrência. Se dois boundaries se solapam,
`asyncio.gather` pode resultar em dados duplicados ou corrompidos.

```python
def test_boundaries_cover_disjoint_regions_for_sibling_functions():
    js = """
    function CompA() { return (<div><Badge /></div>); }
    function CompB() { return (<div><Icon /></div>); }
    """
    from design_graph.core.patterns import RE_COMP_FN
    bounds = find_function_boundaries(js, RE_COMP_FN)
    assert len(bounds) == 2
    a, b = sorted(bounds, key=lambda x: x.start)
    assert a.end <= b.start  # A termina antes de B começar
```

---

## Implementação de `find_function_end`

```python
_SAFETY_LIMIT = 120_000

def find_function_end(js: str, fn_start: int) -> int:
    i = js.find('{', fn_start)
    if i < 0 or i > fn_start + 500:
        return fn_start + 20_000

    depth = 0
    limit = min(fn_start + _SAFETY_LIMIT, len(js))

    while i < limit:
        c = js[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1

    return limit
```

---

## Done when

- [ ] Todos os testes passam, incluindo `test_boundaries_cover_disjoint_regions_for_sibling_functions`
- [ ] `find_function_end` não usa regex — só iteração de chars
- [ ] Nenhum import de `extraction/`, `graph/`, ou `mcp/`
