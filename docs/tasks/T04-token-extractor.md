# T04 — TokenExtractor

**Fase**: 1 — Parsing
**Arquivo**: `src/design_graph/parsing/token_extractor.py`
**Depende de**: `core/models.py` (DesignToken), `core/patterns.py`, `core/constants.py`
**Bloqueia**: T06 (ComponentExtractor — precisa de token_map), T10 (GraphWriter)

---

## Contrato

```python
def extract_tokens(sources: RawSources) -> list[DesignToken]:
    """
    Extrai cores, espaçamentos e demais tokens de design.
    Opera sobre sources.css + sources.js combinados.
    Retorna lista ordenada por: categoria asc, usage desc.
    """

def build_token_map(tokens: list[DesignToken]) -> dict[str, list[DesignToken]]:
    """
    Cria índice value.lower() → [tokens] para lookup rápido por valor.
    Usado por ComponentExtractor para vincular estilos a tokens.
    """
```

---

## TDD

```python
# tests/unit/parsing/test_token_extractor.py

SAMPLE_SOURCES = RawSources(
    js="""
    style={{backgroundColor: '#ffb81c'}}
    style={{backgroundColor: '#ffb81c'}}
    style={{backgroundColor: '#ffb81c'}}
    style={{padding: '16px'}}
    style={{padding: '16px'}}
    style={{padding: '16px'}}
    style={{color: '#ef4444'}}
    style={{color: '#ef4444'}}
    """,
    css="",
    inner_html="",
    html_hash="test",
    format="bundled_react",
)

class TestExtractTokens:
    def test_finds_primary_color(self):
        tokens = extract_tokens(SAMPLE_SOURCES)
        values = {t.value for t in tokens if t.category == "color"}
        assert "#ffb81c" in values

    def test_filters_white_and_black(self):
        sources = RawSources(js="#fff #000 #ffffff #000000 " * 5, ...)
        tokens = extract_tokens(sources)
        values = {t.value for t in tokens}
        assert "#ffffff" not in values
        assert "#000000" not in values

    def test_color_with_one_occurrence_filtered(self):
        sources = RawSources(js="color: '#aabbcc'", ...)  # só 1×
        tokens = extract_tokens(sources)
        assert not any(t.value == "#aabbcc" for t in tokens)

    def test_spacing_normalized_to_4px_grid(self):
        sources = RawSources(js="padding: '14px' " * 3, ...)
        tokens = extract_tokens(sources)
        spacing = [t for t in tokens if t.category == "spacing"]
        values = {t.value for t in spacing}
        assert "16px" in values   # 14 → round(14/4)*4 = 16

    def test_usage_reflects_occurrence_count(self):
        tokens = extract_tokens(SAMPLE_SOURCES)
        primary = next((t for t in tokens if t.value == "#ffb81c"), None)
        assert primary is not None
        assert primary.usage >= 3

    def test_token_ids_are_deterministic(self):
        a = extract_tokens(SAMPLE_SOURCES)
        b = extract_tokens(SAMPLE_SOURCES)
        ids_a = {t.id for t in a}
        ids_b = {t.id for t in b}
        assert ids_a == ids_b

    def test_all_tokens_have_required_fields(self):
        tokens = extract_tokens(SAMPLE_SOURCES)
        for t in tokens:
            assert t.id
            assert t.category in {"color", "spacing"}
            assert t.label
            assert t.value
            assert t.usage >= 1

    def test_returns_at_most_50_color_tokens(self):
        # Build fontes com 100 cores únicas
        many_colors = " ".join(f"'#{'%06x' % i}'" for i in range(100)) * 3
        sources = RawSources(js=many_colors, ...)
        tokens = [t for t in extract_tokens(sources) if t.category == "color"]
        assert len(tokens) <= 50


class TestBuildTokenMap:
    def test_maps_value_to_token(self):
        token = DesignToken(id="col_1", category="color", label="primary",
                            value="#ffb81c", usage=5)
        m = build_token_map([token])
        assert token in m.get("#ffb81c", [])

    def test_key_is_lowercase(self):
        token = DesignToken(id="col_1", category="color", label="x",
                            value="#FFB81C", usage=2)
        m = build_token_map([token])
        assert "#ffb81c" in m   # chave normalizada

    def test_empty_input_returns_empty_map(self):
        assert build_token_map([]) == {}
```

---

## Implementação

### Sub-funções (privadas)

```python
def _extract_colors(combined: str) -> list[DesignToken]: ...
def _extract_spacing(combined: str) -> list[DesignToken]: ...
```

Cada sub-função é testável isoladamente via `extract_tokens` (ao passar sources
com somente js ou css preenchido).

### Label de cor

```python
def _color_label(color: str) -> str:
    """Retorna label semântico de COLOR_LABELS ou o próprio valor."""
    return COLOR_LABELS.get(color, color)
```

---

## Done when

- [ ] Todos os testes passam
- [ ] `extract_tokens(sources_from_simple_html)` produz resultado com pelo menos
      1 token de cor e 1 de espaçamento
- [ ] `build_token_map` usa `value.lower()` como chave — sem variação de case
