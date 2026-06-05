# Plan 02 — Fase 2: Extraction

## Objetivo

Implementar o single-pass extractor, a hierarquia de composição (`child_refs`)
e as estratégias de fallback de seção. O resultado: entidades de domínio
completas sem nenhum double-scan.

## Pré-requisito

Fase 1 completa: `FunctionBoundary`, `RawSources`, `patterns.py` disponíveis.

## Entregáveis

```
src/design_graph/extraction/
  __init__.py
  component_extractor.py
  screen_extractor.py
  section_extractor.py
  (chunker.py — Fase 6)
```

## Sequência TDD

### 2.1 `component_extractor.py`

**Teste de regressão primeiro**: o single-pass deve produzir os mesmos
`styles`, `interactions`, `texts` que o legado para o mesmo JS de entrada.

```python
# tests/unit/extraction/test_component_extractor.py

SIMPLE_COMPONENT_JS = """
function BtnPrimary() {
    return (
        <button
            className="btn-primary"
            style={{backgroundColor: '#ffb81c', padding: '8px'}}
            onMouseEnter={e => e.target.style.backgroundColor = '#f59e0b'}
            onMouseLeave={e => e.target.style.backgroundColor = '#ffb81c'}
        >
            Confirmar
        </button>
    )
}
"""

class TestComponentExtractor:
    def test_single_pass_styles(self):
        # Deve encontrar os mesmos estilos que extract_styles legado

    def test_single_pass_interactions(self):
        # Deve encontrar os mesmos hovers que extract_interactions legado

    def test_single_pass_texts(self):
        # Deve encontrar "Confirmar" como texto de botão

    def test_child_refs_captured(self):
        # NOVO: componentes JSX referenciados capturados em child_refs

    def test_no_double_scan(self):
        # Verificar que o window é percorrido apenas uma vez
        # (pode ser verificado via mock de re.finditer ou contagem)
```

**Teste do child_refs:**

```python
SCREEN_WITH_CHILDREN_JS = """
function RestaurantsPage() {
    return (
        <div>
            <SectionCard restaurant={r} />
            <BtnPrimary onClick={handleOrder} />
            <ConfirmModal isOpen={open} />
        </div>
    )
}
"""

def test_child_refs_found():
    boundary = find_function_boundaries(JS, RE_COMP_FN)[0]
    comp = extract_component(JS, boundary, 1, {})
    assert "SectionCard" in comp.child_refs
    assert "BtnPrimary" in comp.child_refs
    assert "ConfirmModal" in comp.child_refs
```

### 2.2 `screen_extractor.py`

```python
class TestScreenExtractor:
    def test_identifies_page_functions(self):
        # RestaurantsPage → é screen
        # BtnPrimary → não é screen

    def test_identifies_dashboard_functions(self):
        # OrdersDashboard → é screen

    def test_collects_direct_children(self):
        # children de RestaurantsPage inclui SectionCard, BtnPrimary

    def test_does_not_include_internals_as_children(self):
        # Fragment, useState, etc. não aparecem como filhos
```

### 2.3 `section_extractor.py`

```python
class TestSectionExtractor:
    def test_detects_comment_sections(self):
        # {/* ── Header ── */} → seção "Header"

    def test_comment_section_captures_components(self):
        # componentes entre dois comentários são atribuídos à seção correta

    def test_structural_fallback_triggers_without_comments(self):
        # JS sem comentários → fallback estrutural tenta detectar seções

    def test_structural_fallback_finds_padded_divs(self):
        # div com padding:24px → seção candidata

    def test_empty_section_not_created(self):
        # seção sem componentes E sem textos E sem estilos → descartada

    def test_detection_method_recorded(self):
        # seção.detection_method == "comment" quando detectado via comentário
        # seção.detection_method == "structural" quando detectado via padding
```

## Comparação com legado

Para garantir que os resultados não regridem, criar um teste de paridade:

```python
# tests/unit/extraction/test_parity.py
"""
Verifica que os novos extractors produzem resultados equivalentes ao legado
para o fixture simple.html.
"""
from build_graph import extract_all_components as legacy_extract
from design_graph.extraction.component_extractor import extract_all_components as new_extract

class TestParity:
    def test_same_component_names(self, simple_html_js):
        legacy = set(legacy_extract(simple_html_js).keys())
        new_boundaries = find_function_boundaries(simple_html_js, RE_COMP_FN)
        new_names = {b.name for b in new_boundaries}
        # Os novos podem ter mais nomes (captura hierarquia melhor)
        # mas nunca devem perder nomes que o legado encontrava
        assert legacy.issubset(new_names)
```

## Critério de aceite

```bash
pytest tests/unit/extraction/ -v
# Paridade com legado para simple.html
# child_refs populados corretamente
# detection_method registrado em cada seção
```

## Guardrails desta fase

1. `component_extractor` e `screen_extractor` são funções puras — sem side-effects
2. Nenhum extractor cria uma `kuzu.Connection`
3. O `token_map` passado para `extract_component` é read-only (não modificado)
4. `child_refs` não contém o próprio nome do componente (sem auto-referência)
5. O número de `styles` por componente é limitado a 40 (mesmo do legado)
