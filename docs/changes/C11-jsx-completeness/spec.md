# Spec C11 — Extraction: JSX com Rendering Condicional

## Problema

`sanitize_jsx()` remove toda expressão JavaScript do JSX, substituindo por texto
genérico ou removendo completamente. Com isso, o agente perde informações sobre
o **que** é renderizado condicionalmente e **quais** componentes podem aparecer em lista.

### O que é perdido hoje

```jsx
// Input original
{isLoggedIn && <UserMenu />}
{items.map(item => <CartItem key={item.id} />)}
{error ? <ErrorBanner message={error} /> : <SuccessCard />}
```

```jsx
// Output atual de sanitize_jsx
{...}
{...}
{...}
```

O agente não sabe que:
- `UserMenu` é condicional (depende de `isLoggedIn`)
- `CartItem` é renderizado em lista (via `.map`)
- Há alternância entre `ErrorBanner` e `SuccessCard`

## Solução

Substituir expressões dinâmicas por **marcadores tipados** em vez de removê-las:

```jsx
// Output após correção
{[conditional:UserMenu]}
{[list:CartItem]}
{[either:ErrorBanner|SuccessCard]}
```

Esses marcadores são **texto válido dentro de JSX** — preservam a posição visual
e informam o agente sobre o comportamento dinâmico sem expor lógica JavaScript.

## Marcadores definidos

| Padrão original | Marcador | Significado |
|---|---|---|
| `{condition && <Comp />}` | `{[conditional:Comp]}` | Comp aparece condicionalmente |
| `{arr.map(... => <Comp />)}` | `{[list:Comp]}` | Comp aparece em lista |
| `{a ? <CompA /> : <CompB />}` | `{[either:CompA\|CompB]}` | Alternância entre componentes |
| `{expression}` genérico | `{[dynamic]}` | Expressão sem componente identificável |
| `on[handler]` (atual) | mantido | Handlers de evento |
| Style objeto longo | `style={{ k:v, ... }}` (atual) | Resumo do objeto de estilo |

## Contrato

```python
def sanitize_jsx(jsx: str) -> str:
    """
    Strip JavaScript logic from JSX, replacing dynamic expressions with
    typed markers instead of removing them.

    Markers:
      {[conditional:ComponentName]} — short-circuit conditional rendering
      {[list:ComponentName]}        — list rendering via .map()
      {[either:CompA|CompB]}        — ternary between two components
      {[dynamic]}                   — unidentifiable dynamic expression
    """
```

## Invariantes

- Marcadores usam formato `{[tipo:conteúdo]}` — sempre válido como JSX expression string
- Um marcador nunca expõe lógica JS — apenas o padrão estrutural
- `{[conditional:Comp]}` sempre refere um nome PascalCase identificável
- Quando o componente não é identificável: `{[dynamic]}` (nunca omitir)
- A função permanece **pura** — sem side effects, sem I/O
- O log de debug deve contar quantos marcadores foram criados por tipo

## Impacto em `child_refs`

Os componentes identificados dentro de marcadores devem ser adicionados a `child_refs`
da mesma forma que componentes em tags JSX diretas. Isso garante que o CONTAINS
graph capture a dependência mesmo que seja condicional.

```python
# após substituição de {isLoggedIn && <UserMenu />} por {[conditional:UserMenu]}
# UserMenu deve aparecer em child_refs
```

## Arquivos afetados

| Arquivo | Mudança |
|---|---|
| `src/design_graph/extraction/component_extractor.py` | Reescrever `sanitize_jsx()`, atualizar extração de `child_refs` |
| `tests/unit/extraction/test_component_extractor_single_pass_guards.py` | Novos testes de marcadores |

## Escopo desta change

**Inclui:**
- Padrões `&&`, `.map(`, ternários `? A : B`
- child_refs captura componentes dentro dos marcadores

**Não inclui:**
- `@media` queries
- Resolução de valores de props condicionais
- Componentes dentro de funções aninhadas arbitrárias
