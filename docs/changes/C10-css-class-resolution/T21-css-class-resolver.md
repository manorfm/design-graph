# T21 — `css_class_resolver`: Extração e Resolução de Classes CSS

**Change**: C10 — CSS Class Resolution
**Arquivos**:
  - `src/design_graph/parsing/css_class_resolver.py` (novo)
  - `src/design_graph/extraction/component_extractor.py` (adiciona parâmetro)
  - `src/design_graph/pipeline/coordinator.py` (injeta rule_map)
  - `tests/unit/parsing/test_css_class_resolver.py` (novo)
**Depende de**: T01 (source_loader — já extrai CSS), T06 (component_extractor)
**Bloqueia**: nada

---

## Contrato

```python
# parsing/css_class_resolver.py

@dataclass(frozen=True)
class CssRule:
    selector: str    # ".flex"
    property: str    # "display"
    value: str       # "flex"

def extract_css_rules(css_text: str) -> dict[str, list[CssRule]]:
    """Parse CSS → map class_name → rules. Only simple class selectors."""

def resolve_classes(
    class_string: str,
    rule_map: dict[str, list[CssRule]],
) -> list[StyleEntry]:
    """
    Resolve className string using rule_map + Tailwind built-ins.
    Returns StyleEntry list with state="default", source="class".
    Returns [] if class_string is empty or no classes match.
    """
```

```python
# extraction/component_extractor.py — assinatura atualizada
def extract_component(
    js: str,
    boundary: FunctionBoundary,
    occurrence: int,
    token_map: dict[str, list[DesignToken]],
    rule_map: dict[str, list[CssRule]] | None = None,  # NOVO, default None
) -> ExtractedComponent: ...

async def extract_all_components(
    js: str,
    boundaries: list[FunctionBoundary],
    occurrences: Counter,
    token_map: dict[str, list[DesignToken]],
    concurrency: int = 8,
    rule_map: dict[str, list[CssRule]] | None = None,  # NOVO, default None
) -> list[ExtractedComponent]: ...
```

---

## Tailwind Built-ins inclusos nesta task

O subset mínimo para cobertura de ~80% dos protótipos React/Tailwind:

| Classe | CSS gerado |
|---|---|
| `flex` | `display: flex` |
| `block` | `display: block` |
| `hidden` | `display: none` |
| `grid` | `display: grid` |
| `inline-flex` | `display: inline-flex` |
| `items-center` | `align-items: center` |
| `items-start` | `align-items: flex-start` |
| `justify-center` | `justify-content: center` |
| `justify-between` | `justify-content: space-between` |
| `gap-1..gap-12` | `gap: {n*0.25}rem` |
| `p-1..p-8` | `padding: {n*0.25}rem` |
| `px-1..px-8` | `padding-left/right: {n*0.25}rem` |
| `py-1..py-8` | `padding-top/bottom: {n*0.25}rem` |
| `text-xs..text-4xl` | `font-size: ...` |
| `font-normal/medium/semibold/bold` | `font-weight: ...` |
| `rounded/rounded-md/rounded-lg/rounded-full` | `border-radius: ...` |
| `w-full/h-full` | `width/height: 100%` |
| `overflow-hidden` | `overflow: hidden` |
| `truncate` | `overflow + ellipsis + nowrap` |
| `relative/absolute/fixed` | `position: ...` |
| `inset-0` | `inset: 0` |
| `z-10/z-20/z-50` | `z-index: 10/20/50` |

---

## TDD (resumo — detalhes no plan.md)

**RED:** 15 testes em `test_css_class_resolver.py` (ver plan.md)

**GREEN:**
1. Implementar `extract_css_rules` com regex simples
2. Implementar `resolve_classes` com fallback ao built-in map
3. Adicionar `rule_map=None` a `extract_component` e `extract_all_components`
4. Em `coordinator.py`: `rule_map = extract_css_rules(sources.css)` antes da extração

**BLUE:**
- Mover `_TAILWIND_BUILTINS` para `core/constants.py` se > 30 linhas
- Verificar que nenhum teste existente quebra (parâmetro opcional)

---

## Done when

- [ ] `extract_css_rules` parseia seletores simples `.classname { prop: val; }`
- [ ] `extract_css_rules` ignora pseudo-classes, @media, seletores de tag/ID
- [ ] `resolve_classes("flex gap-4", {})` retorna StyleEntry com `display:flex` e `gap:1rem`
- [ ] CSS real do protótipo vence o built-in (precedência de `rule_map`)
- [ ] `source="class"` em todas as entries geradas por resolução de classe
- [ ] `extract_component` aceita `rule_map=None` sem breaking change
- [ ] Guardrail G1: `css_class_resolver.py` não importa de extraction/graph/mcp
- [ ] Todos os testes existentes continuam passando
