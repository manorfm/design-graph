# Plan C10 — CSS Class Resolution

## Objetivo

Criar `css_class_resolver.py` e integrar à pipeline para que classes Tailwind/CSS
sejam resolvidas em `StyleEntry` com valores reais, aumentando de ~50% para ~75%
a cobertura de estilos.

## Critério de aceite

```bash
pytest tests/unit/parsing/test_css_class_resolver.py -v      # novos testes verdes
pytest tests/unit/extraction/ -v                              # sem regressão
pytest tests/integration/test_pipeline.py -v                  # integração verde
```

## Sequência TDD

### Fase 1: `parsing/css_class_resolver.py`

**RED — escrever testes:**

```python
# tests/unit/parsing/test_css_class_resolver.py

from design_graph.parsing.css_class_resolver import (
    CssRule, extract_css_rules, resolve_classes
)

class TestExtractCssRules:
    def test_simple_class_selector(self):
        css = ".btn { display: flex; padding: 8px; }"
        rules = extract_css_rules(css)
        assert "btn" in rules
        props = {r.property: r.value for r in rules["btn"]}
        assert props["display"] == "flex"
        assert props["padding"] == "8px"

    def test_multiple_classes(self):
        css = ".flex { display: flex; } .hidden { display: none; }"
        rules = extract_css_rules(css)
        assert "flex" in rules
        assert "hidden" in rules

    def test_ignores_element_selectors(self):
        css = "div { margin: 0; } .card { padding: 16px; }"
        rules = extract_css_rules(css)
        assert "div" not in rules
        assert "card" in rules

    def test_ignores_pseudo_classes(self):
        css = ".btn:hover { background: red; }"
        rules = extract_css_rules(css)
        assert "btn" not in rules  # pseudo-class — fora do escopo

    def test_empty_css_returns_empty_dict(self):
        assert extract_css_rules("") == {}

    def test_malformed_css_does_not_raise(self):
        result = extract_css_rules("this is not css {{{{")
        assert isinstance(result, dict)

    def test_returns_dict_of_class_to_rules(self):
        css = ".primary { color: #ffb81c; font-weight: 700; }"
        rules = extract_css_rules(css)
        assert "primary" in rules
        assert len(rules["primary"]) == 2


class TestResolveClasses:
    def test_known_class_resolves(self):
        rule_map = {"flex": [CssRule(".flex", "display", "flex")]}
        entries = resolve_classes("flex items-center", rule_map)
        props = {e.property: e.value for e in entries}
        assert props.get("display") == "flex"

    def test_unknown_class_ignored(self):
        entries = resolve_classes("unknown-class-xyz", {})
        assert entries == []

    def test_tailwind_builtin_flex_resolved(self):
        # sem rule_map customizado — usa built-ins
        entries = resolve_classes("flex gap-4", {})
        props = {e.property: e.value for e in entries}
        assert props.get("display") == "flex"
        assert props.get("gap") == "1rem"

    def test_source_is_class(self):
        entries = resolve_classes("flex", {})
        for e in entries:
            assert e.source == "class"  # rastreável

    def test_element_contains_class_name(self):
        entries = resolve_classes("flex", {})
        for e in entries:
            assert "flex" in e.element

    def test_empty_class_string_returns_empty(self):
        assert resolve_classes("", {}) == []

    def test_custom_rule_overrides_tailwind_builtin(self):
        # CSS real define .flex diferente do built-in
        custom_map = {"flex": [CssRule(".flex", "display", "grid")]}
        entries = resolve_classes("flex", custom_map)
        props = {e.property: e.value for e in entries}
        assert props["display"] == "grid"  # custom vence
```

**GREEN — implementação mínima:**
```python
# src/design_graph/parsing/css_class_resolver.py

import re
from dataclasses import dataclass
from design_graph.core.models import StyleEntry
import hashlib

@dataclass(frozen=True)
class CssRule:
    selector: str
    property: str
    value: str

_RE_CLASS_RULE = re.compile(
    r'\.([a-zA-Z][a-zA-Z0-9_-]*)\s*\{([^}]+)\}',
    re.MULTILINE,
)
_RE_PROPERTY = re.compile(r'([a-z-]+)\s*:\s*([^;]+);?')

def extract_css_rules(css_text: str) -> dict[str, list[CssRule]]:
    result: dict[str, list[CssRule]] = {}
    for m in _RE_CLASS_RULE.finditer(css_text):
        cls_name = m.group(1)
        body = m.group(2)
        rules = []
        for pm in _RE_PROPERTY.finditer(body):
            prop = pm.group(1).strip()
            val = pm.group(2).strip()
            if prop and val:
                rules.append(CssRule(f".{cls_name}", prop, val))
        if rules:
            result[cls_name] = rules
    return result

def resolve_classes(
    class_string: str,
    rule_map: dict[str, list[CssRule]],
) -> list[StyleEntry]:
    if not class_string.strip():
        return []
    entries: list[StyleEntry] = []
    seen: set[str] = set()
    for cls in class_string.split():
        rules = rule_map.get(cls) or [
            CssRule(f".{cls}", prop, val)
            for prop, val in _TAILWIND_BUILTINS.get(cls, [])
        ]
        for rule in rules:
            key = f"{cls}:{rule.property}"
            if key not in seen:
                seen.add(key)
                sid = f"cls_{hashlib.md5(key.encode()).hexdigest()[:8]}"
                entries.append(StyleEntry(
                    id=sid, element=f"class:{cls}", state="default",
                    property=rule.property, value=rule.value, source="class",
                ))
    return entries
```

**BLUE — refinar:** extrair `_TAILWIND_BUILTINS` para `core/constants.py` se ficar grande.

### Fase 2: integração na `extraction/component_extractor.py`

Adicionar parâmetro opcional `rule_map` a `extract_component` e `extract_all_components`.
Nenhum teste existente deve quebrar (parâmetro com default `None`).

### Fase 3: integração na `pipeline/coordinator.py`

```python
from design_graph.parsing.css_class_resolver import extract_css_rules
...
rule_map = extract_css_rules(sources.css) if sources.css else {}
logger.info("pipeline: %d CSS classes resolved from stylesheet", len(rule_map))
```

## Guardrail G1

`parsing/css_class_resolver.py` **não pode** importar de `extraction/`, `graph/` ou `mcp/`.
Adicionar guardrail test:
```python
def test_css_class_resolver_layer_isolation():
    import ast, pathlib
    src = pathlib.Path("src/design_graph/parsing/css_class_resolver.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            ...  # verificar que não importa extraction/graph/mcp
```
