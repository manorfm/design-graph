# Plan C11 — JSX Completeness

## Objetivo

Reescrever `sanitize_jsx()` para substituir expressões dinâmicas por marcadores
tipados em vez de removê-las, preservando informação de estrutura condicional e
de lista para consumo por agentes de IA.

## Critério de aceite

```bash
pytest tests/unit/extraction/test_component_extractor_single_pass_guards.py \
       -k "marker or conditional or list or ternary" -v
# todos os novos testes verdes

pytest tests/unit/extraction/ -v  # sem regressão
```

## Sequência TDD

### Fase 1: `sanitize_jsx` — marcadores condicionais

**RED:**
```python
class TestSanitizeJsxMarkers:
    def test_short_circuit_conditional_gets_marker(self):
        jsx = "<div>{isLoggedIn && <UserMenu />}</div>"
        result = sanitize_jsx(jsx)
        assert "[conditional:UserMenu]" in result
        assert "isLoggedIn" not in result  # lógica removida

    def test_map_list_gets_marker(self):
        jsx = "<ul>{items.map(item => <CartItem key={item.id} />)}</ul>"
        result = sanitize_jsx(jsx)
        assert "[list:CartItem]" in result
        assert "items.map" not in result

    def test_ternary_with_two_components(self):
        jsx = "<div>{error ? <ErrorBanner /> : <SuccessCard />}</div>"
        result = sanitize_jsx(jsx)
        assert "[either:ErrorBanner|SuccessCard]" in result
        assert "error ?" not in result

    def test_unidentifiable_expression_gets_dynamic_marker(self):
        jsx = "<div>{someComplexExpression()}</div>"
        result = sanitize_jsx(jsx)
        assert "[dynamic]" in result

    def test_static_text_unchanged(self):
        jsx = "<div>Hello World</div>"
        result = sanitize_jsx(jsx)
        assert "Hello World" in result

    def test_style_handler_still_collapsed(self):
        jsx = '<div onMouseEnter={() => setState({hovered: true})} />'
        result = sanitize_jsx(jsx)
        assert "on[handler]" in result
        assert "setState" not in result

    def test_inline_style_still_summarized(self):
        long_style = "style={{ " + ", ".join(f"prop{i}: 'val{i}'" for i in range(20)) + " }}"
        jsx = f"<div {long_style} />"
        result = sanitize_jsx(jsx)
        assert "..." in result  # resumido

    def test_marker_format_is_bracket_notation(self):
        jsx = "<div>{flag && <Modal />}</div>"
        result = sanitize_jsx(jsx)
        assert "{[conditional:Modal]}" in result

    def test_child_component_not_omitted_from_output(self):
        jsx = "<div>{flag && <SomeComponent />}<Other /></div>"
        result = sanitize_jsx(jsx)
        assert "SomeComponent" in result
        assert "Other" in result
```

### Fase 2: `child_refs` captura componentes em marcadores

Os componentes dentro de `{[conditional:X]}`, `{[list:X]}` e `{[either:X|Y]}`
devem ser adicionados a `child_refs`. A regex `RE_COMP_REF` e `RE_JSX_TAG` não
capturam marcadores — adicionar um regex específico ou processar o output de
`sanitize_jsx` para extrair nomes dos marcadores.

```python
_RE_MARKER_COMP = re.compile(r'\[(?:conditional|list|either):([A-Z][A-Za-z0-9]*(?:\|[A-Z][A-Za-z0-9]*)*)\]')

def _extract_marker_refs(sanitized_jsx: str) -> set[str]:
    refs: set[str] = set()
    for m in _RE_MARKER_COMP.finditer(sanitized_jsx):
        for name in m.group(1).split("|"):
            if len(name) >= 3:
                refs.add(name)
    return refs
```

**RED:**
```python
class TestChildRefsFromMarkers:
    def test_conditional_comp_in_child_refs(self):
        js = """
        function Screen() {
            return <div>{isOpen && <UserMenu />}</div>;
        }
        """
        boundary = FunctionBoundary(name="Screen", start=0, end=len(js))
        comp = extract_component(js, boundary, 1, {})
        assert "UserMenu" in comp.child_refs

    def test_list_comp_in_child_refs(self):
        js = """
        function Screen() {
            return <ul>{items.map(i => <CartItem />)}</ul>;
        }
        """
        boundary = FunctionBoundary(name="Screen", start=0, end=len(js))
        comp = extract_component(js, boundary, 1, {})
        assert "CartItem" in comp.child_refs

    def test_ternary_both_comps_in_child_refs(self):
        js = """
        function Screen() {
            return <div>{err ? <ErrComp /> : <OkComp />}</div>;
        }
        """
        boundary = FunctionBoundary(name="Screen", start=0, end=len(js))
        comp = extract_component(js, boundary, 1, {})
        assert "ErrComp" in comp.child_refs
        assert "OkComp" in comp.child_refs
```

### Fase 3: logging de marcadores

```python
logger.debug(
    "sanitize_jsx: %d conditional, %d list, %d ternary, %d dynamic markers inserted",
    n_conditional, n_list, n_ternary, n_dynamic,
)
```

## Implementação de `sanitize_jsx` (GREEN)

Ordem de substituição (importa para evitar conflitos de regex):

1. Event handlers (atual: `on[handler]`)
2. `.map(...)` → `{[list:Comp]}`
3. `{expr && <Comp />}` → `{[conditional:Comp]}`
4. `{expr ? <CompA /> : <CompB />}` → `{[either:CompA|CompB]}`
5. `{expr}` genérico → `{[dynamic]}`
6. Long style objects (atual: `style={{ ... }}`)
7. Triple+ newlines (atual)

## Regex a implementar

```python
# .map(... => <Comp />)
RE_MAP_RENDER = re.compile(
    r'\{[^}]{0,50}\.map\([^)]{0,80}\s*=>\s*<([A-Z][A-Za-z0-9]*)[^}]{0,200}\}\)',
    re.DOTALL,
)

# {expr && <Comp />}
RE_SHORT_CIRCUIT = re.compile(
    r'\{[^{}<>]{1,80}&&\s*<([A-Z][A-Za-z0-9]*)[^}]{0,200}\}',
    re.DOTALL,
)

# {expr ? <CompA /> : <CompB />}
RE_TERNARY_COMP = re.compile(
    r'\{[^{}<>]{1,80}\?\s*<([A-Z][A-Za-z0-9]*)[^}]{0,100}>\s*:\s*<([A-Z][A-Za-z0-9]*)[^}]{0,100}\}',
    re.DOTALL,
)

# {expr} genérico (após as anteriores)
RE_GENERIC_EXPR = re.compile(r'\{[^}]{3,}\}')
```

## Guardrails

- G4: `sanitize_jsx` é síncrona e pura
- Sem import de `graph/` ou `mcp/` no arquivo
- Nenhum teste existente de `sanitize_jsx` deve quebrar (adicionar — não remover)
