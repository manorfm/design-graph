# T22 — `sanitize_jsx`: Marcadores Tipados para Rendering Dinâmico

**Change**: C11 — JSX Completeness
**Arquivo**: `src/design_graph/extraction/component_extractor.py`
**Depende de**: T06 (component_extractor)
**Bloqueia**: nada

---

## Contexto

`sanitize_jsx` substitui toda expressão JS por `{...}`, perdendo informação sobre
quais componentes são condicionais, em lista ou alternados. Um agente que lê o JSX
sanitizado hoje não sabe que `<RestaurantsPage>` renderiza `<UserMenu>` condicionalmente.

---

## Contrato

```python
def sanitize_jsx(jsx: str) -> str:
    """
    Strip JS logic, replacing dynamic expressions with typed markers:
      {[conditional:CompName]}    — short-circuit rendering
      {[list:CompName]}           — .map() list rendering
      {[either:CompA|CompB]}      — ternary between components
      {[dynamic]}                 — unidentifiable expression
    Component names in markers are also added to child_refs.
    """
```

Novo helper (privado):
```python
def _extract_marker_refs(sanitized_jsx: str) -> set[str]:
    """Extract PascalCase names from typed markers in sanitized JSX."""
```

---

## Ordem de substituição em `sanitize_jsx`

1. `RE_LONG_EVENT_HANDLER` → `"on[handler]"` *(existente)*
2. `RE_LONG_ARROW_FN` → `".[fn]"` *(existente)*
3. `RE_MAP_RENDER` → `"{[list:Comp]}"` *(novo)*
4. `RE_SHORT_CIRCUIT` → `"{[conditional:Comp]}"` *(novo)*
5. `RE_TERNARY_COMP` → `"{[either:CompA|CompB]}"` *(novo)*
6. `RE_GENERIC_EXPR` → `"{[dynamic]}"` *(novo, somente expressões > 20 chars)*
7. Long style collapse *(existente)*
8. Triple newlines *(existente)*

**Importante**: processar na ordem acima. `.map()` antes de `&&` evita sobreposição.

---

## Regex novos (em `core/patterns.py`)

```python
# {items.map(item => <CartItem ... />)}
RE_MAP_RENDER = re.compile(
    r'\{[^{}<>]{0,60}\.map\([^)]{0,100}\s*=>\s*(?:\([^)]*\)|\s*)<([A-Z][A-Za-z0-9]+)[^}]{0,300}\}',
    re.DOTALL,
)

# {flag && <Component />} or {flag && <Component>...</Component>}
RE_SHORT_CIRCUIT = re.compile(
    r'\{[^{}<>&&]{1,100}&&\s*<([A-Z][A-Za-z0-9]+)[^}]{0,300}\}',
    re.DOTALL,
)

# {cond ? <CompA ... /> : <CompB ... />}
RE_TERNARY_COMP = re.compile(
    r'\{[^{}<>?]{1,100}\?\s*<([A-Z][A-Za-z0-9]+)[^:]{0,200}:\s*<([A-Z][A-Za-z0-9]+)[^}]{0,200}\}',
    re.DOTALL,
)

# Expressão genérica {expr} com mais de 20 chars (após os anteriores)
RE_GENERIC_LONG_EXPR = re.compile(r'\{[^{}]{20,}\}', re.DOTALL)
```

---

## TDD

```python
# tests/unit/extraction/test_component_extractor_single_pass_guards.py

class TestSanitizeJsxTypedMarkers:
    def test_map_renders_list_marker(self):
        jsx = "<ul>{items.map(i => <CartItem key={i.id} />)}</ul>"
        assert "[list:CartItem]" in sanitize_jsx(jsx)

    def test_short_circuit_renders_conditional_marker(self):
        jsx = "<div>{isOpen && <Modal />}</div>"
        assert "[conditional:Modal]" in sanitize_jsx(jsx)

    def test_ternary_renders_either_marker(self):
        jsx = "<div>{err ? <ErrComp /> : <OkComp />}</div>"
        result = sanitize_jsx(jsx)
        assert "[either:ErrComp|OkComp]" in result

    def test_generic_expression_gets_dynamic_marker(self):
        jsx = "<div>{someFunction().result.value}</div>"
        result = sanitize_jsx(jsx)
        assert "[dynamic]" in result

    def test_static_content_unchanged(self):
        jsx = "<h1>Título fixo</h1>"
        assert "Título fixo" in sanitize_jsx(jsx)

    def test_marker_format_is_bracket_notation(self):
        result = sanitize_jsx("<div>{flag && <Comp />}</div>")
        assert result.count("{[") >= 1
        assert result.count("]}") >= 1

    def test_no_js_logic_exposed(self):
        jsx = "<div>{isLoggedIn && <UserMenu />}</div>"
        result = sanitize_jsx(jsx)
        assert "isLoggedIn" not in result
        assert "&&" not in result

    def test_handler_still_collapsed(self):
        jsx = '<div onMouseEnter={() => setHovered(true)} />'
        result = sanitize_jsx(jsx)
        assert "on[handler]" in result
        assert "setHovered" not in result

    def test_multiple_markers_in_same_jsx(self):
        jsx = """
        <div>
          {items.map(i => <Item />)}
          {isAdmin && <AdminPanel />}
        </div>
        """
        result = sanitize_jsx(jsx)
        assert "[list:Item]" in result
        assert "[conditional:AdminPanel]" in result


class TestChildRefsFromMarkers:
    def _boundary(self, name: str, js: str) -> FunctionBoundary:
        return FunctionBoundary(name=name, start=0, end=len(js))

    def test_conditional_comp_in_child_refs(self):
        js = "function S() { return <div>{flag && <UserMenu />}</div>; }"
        comp = extract_component(js, self._boundary("S", js), 1, {})
        assert "UserMenu" in comp.child_refs

    def test_list_comp_in_child_refs(self):
        js = "function S() { return <ul>{items.map(i => <CartItem />)}</ul>; }"
        comp = extract_component(js, self._boundary("S", js), 1, {})
        assert "CartItem" in comp.child_refs

    def test_ternary_both_comps_in_child_refs(self):
        js = "function S() { return <div>{ok ? <SuccessCard /> : <ErrorBanner />}</div>; }"
        comp = extract_component(js, self._boundary("S", js), 1, {})
        assert "SuccessCard" in comp.child_refs
        assert "ErrorBanner" in comp.child_refs

    def test_marker_refs_deduplicated_with_direct_refs(self):
        # CartItem aparece como tag direta E no map — deve aparecer 1× em child_refs
        js = "function S() { return <div><CartItem />{items.map(i => <CartItem />)}</div>; }"
        comp = extract_component(js, self._boundary("S", js), 1, {})
        assert comp.child_refs.count("CartItem") == 1
```

---

## Done when

- [ ] `sanitize_jsx` insere marcadores `{[conditional:X]}`, `{[list:X]}`, `{[either:X|Y]}`, `{[dynamic]}`
- [ ] Nenhuma lógica JS (nomes de variáveis, `&&`, `? :`, `.map(`) fica exposta
- [ ] Novos regex adicionados a `core/patterns.py`
- [ ] `_extract_marker_refs` extrai PascalCase de marcadores
- [ ] `extract_component` chama `_extract_marker_refs` e adiciona ao `child_refs`
- [ ] Todos os 12 testes acima passam
- [ ] Testes existentes de `sanitize_jsx` não regridem
- [ ] G4: `sanitize_jsx` é síncrona e pura (sem side effects)
