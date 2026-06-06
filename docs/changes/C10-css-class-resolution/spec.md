# Spec C10 — Parsing: Resolução de Classes CSS

## Problema

Componentes React usam `className` com classes Tailwind ou custom CSS. O extrator
atual captura os nomes das classes (ex: `"flex items-center gap-4 bg-primary"`),
mas não resolve para valores CSS reais. Isso significa que ~50% dos estilos
ficam ocultos ao agente.

Exemplos de perguntas impossíveis hoje:
- "Qual o padding real do BtnPrimary?" → Tailwind `px-6` = `padding-left: 1.5rem; padding-right: 1.5rem` — perdido
- "O CartItem usa flexbox?" → `flex` é classe, não style inline — perdido
- "Quais componentes têm gap de 16px?" → `gap-4` = `1rem = 16px` — irresolúvel

## Solução

Extrair as regras CSS dos `<style>` tags e folhas de estilo referenciadas no HTML
e criar um mapa de `class_name → [property: value]`. Durante a extração de componentes,
usar esse mapa para resolver as classes em `StyleEntry` adicionais com `source="class"`.

## Arquitetura

### Novo módulo: `parsing/css_class_resolver.py`

```python
@dataclass(frozen=True)
class CssRule:
    selector: str   # ".flex", ".bg-primary", ".px-6"
    property: str   # "display", "background-color", "padding-left"
    value: str      # "flex", "#ffb81c", "1.5rem"

def extract_css_rules(css_text: str) -> dict[str, list[CssRule]]:
    """
    Parse CSS text → map from class name → list of CssRule.
    Only simple class selectors (.classname { property: value }).
    Ignores pseudo-classes, @media, :hover, etc. (em escopo desta change).
    """

def resolve_classes(class_string: str, rule_map: dict[str, list[CssRule]]) -> list[StyleEntry]:
    """
    Given a className string like "flex items-center gap-4",
    return StyleEntry list for each known class.
    state = "default", element = "class:{class_name}"
    """
```

### Tailwind Built-in Map

Para Tailwind classes que não aparecem no CSS gerado (o JIT pode não gerar todas),
manter um subset das utilidades mais comuns como fallback:

```python
_TAILWIND_BUILTINS: dict[str, list[tuple[str, str]]] = {
    "flex":        [("display", "flex")],
    "block":       [("display", "block")],
    "hidden":      [("display", "none")],
    "items-center": [("align-items", "center")],
    "justify-center": [("justify-content", "center")],
    "gap-1":       [("gap", "0.25rem")],
    "gap-2":       [("gap", "0.5rem")],
    "gap-4":       [("gap", "1rem")],
    "gap-6":       [("gap", "1.5rem")],
    "gap-8":       [("gap", "2rem")],
    "p-2":         [("padding", "0.5rem")],
    "p-4":         [("padding", "1rem")],
    "p-6":         [("padding", "1.5rem")],
    "px-4":        [("padding-left", "1rem"), ("padding-right", "1rem")],
    "px-6":        [("padding-left", "1.5rem"), ("padding-right", "1.5rem")],
    "py-2":        [("padding-top", "0.5rem"), ("padding-bottom", "0.5rem")],
    "py-4":        [("padding-top", "1rem"), ("padding-bottom", "1rem")],
    "text-sm":     [("font-size", "0.875rem")],
    "text-base":   [("font-size", "1rem")],
    "text-lg":     [("font-size", "1.125rem")],
    "text-xl":     [("font-size", "1.25rem")],
    "font-medium": [("font-weight", "500")],
    "font-bold":   [("font-weight", "700")],
    "rounded":     [("border-radius", "0.25rem")],
    "rounded-md":  [("border-radius", "0.375rem")],
    "rounded-lg":  [("border-radius", "0.5rem")],
    "rounded-full": [("border-radius", "9999px")],
    "w-full":      [("width", "100%")],
    "h-full":      [("height", "100%")],
    "overflow-hidden": [("overflow", "hidden")],
    "truncate":    [("overflow", "hidden"), ("text-overflow", "ellipsis"), ("white-space", "nowrap")],
    # ... expandível
}
```

### Integração na Pipeline

`RawSources` já expõe `css`. O `coordinator.py` passa o CSS ao resolver antes da
extração de componentes. O resultado é um `rule_map` injetado em `extract_component`.

```python
# pipeline/coordinator.py
rule_map = extract_css_rules(sources.css)
```

```python
# extraction/component_extractor.py
def extract_component(js, boundary, occurrence, token_map, rule_map=None):
    ...
    if rule_map and comp.classes:
        class_styles = resolve_classes(comp.classes, rule_map)
        styles.extend(class_styles[:MAX_STYLES_PER_COMPONENT - len(styles)])
```

## Invariantes

- `extract_css_rules` é **pura** — nenhum I/O, apenas string in → dict out
- `resolve_classes` é **pura** — nenhum I/O, sem side effects
- Estilos de classe têm `source="class"` para distinguir de inline styles (`source=""`)
- A StyleEntry de classe usa `element = "class:{class_name}"` para rastreabilidade
- O built-in map é um **fallback** — se o CSS real define a classe, o CSS real vence
- `rule_map=None` é o default — a extração sem CSS funciona como antes (sem breaking change)

## Escopo desta change

**Inclui:**
- Seletores simples: `.classname { property: value; }`
- Tailwind built-in fallback map (~30 classes mais comuns)
- Integração ao pipeline via parâmetro opcional

**Não inclui:**
- `@media` queries (escopo de C11 ou posterior)
- `:hover`, `:focus` pseudo-classes (escopo de C11)
- `@apply` directives
- CSS modules ou CSS-in-JS

## Arquivos afetados

| Arquivo | Mudança |
|---|---|
| `src/design_graph/parsing/css_class_resolver.py` | **Novo módulo** |
| `src/design_graph/extraction/component_extractor.py` | +parâmetro `rule_map` em `extract_component` |
| `src/design_graph/pipeline/coordinator.py` | Injeta `rule_map` na extração |
| `tests/unit/parsing/test_css_class_resolver.py` | **Novo arquivo de testes** |
| `tests/unit/extraction/test_component_extractor_single_pass_guards.py` | Testes com `rule_map` |
