# Spec 02 — Módulo `extraction/`

## Responsabilidade

Transformar dados brutos de `parsing/` em entidades de domínio semânticas:
`Component`, `Screen`, `Section`, `Chunk`. Estes módulos são os únicos que
interpretam significado — um `div` com `role=navigation` se torna um `Component`
do tipo `"navigation"` aqui, não no parsing.

## Princípio central

> Extraction é transformação. Entrada: RawSources + FunctionBoundary.
> Saída: entidades de domínio tipadas.
> Cada extractor tem uma única responsabilidade e pode ser testado isoladamente
> com strings de JS/HTML fabricadas em teste — sem arquivo HTML real.

---

## 1. `component_extractor.py`

### Problema atual

O `build_graph.py` percorre `js[fn_start : fn_start + 14000]` **cinco vezes**
(jsx, styles, interactions, texts, classes) por componente.
Para 100 componentes, são 500 varreduras de string, muitas com overlap.

### Solução: single-pass via `FunctionBoundary`

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
    child_refs: list[str]   # NOVO: componentes referenciados no JSX deste componente

def extract_component(
    js: str,
    boundary: FunctionBoundary,
    occurrence: int,
    token_map: dict[str, list],   # value.lower() → [DesignToken]
) -> ExtractedComponent:
    """
    Extrai todos os dados de um componente em uma única varredura do seu corpo.
    Recebe a FunctionBoundary já calculada por js_parser — não precisa procurar.
    """
```

### Algoritmo single-pass

```python
def extract_component(js, boundary, occurrence, token_map):
    # 1. Recortar exatamente o corpo da função (sem busca)
    window = js[boundary.start : boundary.end]

    # 2. Extrair JSX do return() — uma única chamada
    jsx_raw = extract_return_block(js, boundary.start, boundary.end)
    jsx_snippet = sanitize_jsx(jsx_raw)

    # 3. Uma única varredura do window para:
    styles, interactions, texts, classes = [], [], [], set()
    child_refs = set()

    for m in RE_INLINE_STYLE.finditer(window):
        # acumula styles...

    for m in RE_MOUSE_ENTER.finditer(window):
        # acumula hover interactions...

    for m in RE_JSX_TAG.finditer(window):
        c = m.group(1)
        if c not in INTERNALS and c != boundary.name:
            child_refs.add(c)   # NOVO: hierarquia

    for m in RE_UI_STRING.finditer(window):
        # acumula texts...

    for m in RE_CLASS_NAME.finditer(window):
        for cls in m.group(1).split():
            classes.add(cls)

    return ExtractedComponent(
        name=boundary.name,
        comp_type=infer_type(boundary.name),
        jsx_snippet=jsx_snippet,
        occurrence=occurrence,
        classes=' '.join(list(classes)[:10]),
        styles=styles[:40],
        interactions=interactions[:15],
        texts=texts[:30],
        child_refs=sorted(child_refs),
    )
```

### Contrato de `extract_all_components`

```python
async def extract_all_components(
    js: str,
    boundaries: list[FunctionBoundary],
    occurrences: Counter,
    token_map: dict,
    concurrency: int = 8,
) -> list[ExtractedComponent]:
    """
    Extrai todos os componentes de forma concorrente.
    Cada componente usa sua própria FunctionBoundary — sem overlap de janelas.
    """
```

### Segurança de concorrência

- `js` é uma string Python (imutável) — múltiplas coroutines lendo em paralelo é seguro
- Cada `ExtractedComponent` é um novo objeto — sem estado compartilhado mutável
- `asyncio.Semaphore(concurrency)` previne sobrecarga de CPU com muitos componentes
- Resultado é coletado via `asyncio.gather(*tasks)` e ordenado no final

---

## 2. `screen_extractor.py`

### Responsabilidade

Identificar quais funções são "telas" (nome termina em Page/Screen/Dashboard/etc.)
e mapear quais componentes cada tela referencia diretamente.

### Contrato

```python
@dataclass
class ExtractedScreen:
    name: str
    component_refs: list[str]   # componentes referenciados diretamente na tela
    sections_count: int         # preenchido após section_extractor rodar

def extract_screens(
    js: str,
    all_boundaries: list[FunctionBoundary],
) -> list[ExtractedScreen]:
    """
    Filtra boundaries de telas (usando RE_PAGE_FN como critério).
    Para cada tela, encontra referências a componentes no corpo.
    """
```

### Critério de Screen vs Component

Um `FunctionBoundary` é Screen se o nome satisfaz:
```python
RE_SCREEN_NAME = re.compile(
    r'^[A-Z][a-zA-Z]+'
    r'(?:Page|Screen|Dashboard|Detail|Panel|View|Tab|Section|List|Form|Modal)$'
)
```

Este regex fica em `core/patterns.py` — não duplicado em screen_extractor.

### Coleta de referências

Dentro do corpo da função tela, coletar:
- Tags JSX: `RE_JSX_TAG` (ex: `<SectionCard />`)
- Chamadas transpiladas: `RE_JSX_CALL` (ex: `jsx(SectionCard, ...)`)
- Referências de nome: `RE_COMP_REF` (ex: variáveis com sufixo Card/Modal/etc.)

Exclusões: o próprio nome da tela e `INTERNALS`.

---

## 3. `section_extractor.py`

### Responsabilidade

Detectar seções visuais dentro de uma tela. Estratégia em cascata:
1. **Comentários JSX** `{/* ── Nome ── */}` (funciona no protótipo iPede)
2. **Fallback estrutural**: blocos `<div>` com padding/margin significativo
3. **Fallback semântico**: tags HTML5 (`<nav>`, `<header>`, `<main>`, `<footer>`, `<section>`)

### Contrato

```python
@dataclass
class ExtractedSection:
    id: str
    screen: str
    name: str
    styles: dict[str, str]
    component_refs: list[str]
    texts: list[str]
    jsx_snippet: str
    detection_method: str   # "comment" | "structural" | "semantic" | "none"

def extract_sections(
    js: str,
    screen: ExtractedScreen,
    boundary: FunctionBoundary,
) -> list[ExtractedSection]:
    """
    Tenta detectar seções em ordem de confiabilidade.
    Retorna lista vazia se nenhum método funcionar (não cria seção artificial).
    """
```

### Estratégia 1: Comentários JSX

Detecta `{/* ── Header ── */}` e considera tudo até o próximo comentário como a seção.

```python
RE_SECTION_COMMENT = re.compile(
    r'\{/\*\s*[─━\-=*]{0,6}\s*(.{2,40}?)\s*[─━\-=*]{0,6}\s*\*/\}'
)
```

### Estratégia 2: Fallback estrutural

Quando não há comentários, detectar `<div>` com `padding` ou `margin` >= 16px
como potenciais divisores de seção. Nomear pelo primeiro texto encontrado dentro.

```python
def _detect_structural_sections(window: str, screen_name: str) -> list[ExtractedSection]:
    # Procura divs com padding/margin substanciais (>= 16px)
    # Considera o primeiro texto filho como nome da seção
    # Retorna no máximo 8 seções (evita fragmentação excessiva)
```

### Estratégia 3: Fallback semântico (plain HTML)

Quando o inner_html tem tags semânticas, usar `BeautifulSoup` para detectar
`<nav>`, `<header>`, `<main>`, `<aside>`, `<section>`, `<footer>` como seções.

### Invariante de qualidade

Uma seção só é criada se tiver:
- Pelo menos 1 componente referenciado, OU
- Pelo menos 2 textos, OU
- Pelo menos 3 propriedades de estilo

Isso evita seções vazias que poluem o grafo.

---

## 4. `chunker.py`

### Responsabilidade

Transformar os dados extraídos em chunks autocontidos para consumo por IAs.
Cada chunk tem um envelope de contexto que permite entendê-lo sem ler os outros.

### Contrato

```python
@dataclass
class ChunkEnvelope:
    chunk_id: str           # ex: "menu_page__header"
    breadcrumb: str         # ex: "MenuPage > Header"
    level: str              # "screen" | "section" | "component"
    parent_id: str | None
    sibling_ids: list[str]
    content: str            # JSX sanitizado ou estrutura HTML
    tokens_est: int         # estimativa de tokens (chars / 4)
    component_refs: list[str]
    context_summary: str    # resumo em 1 linha gerado por template

def chunk_extracted_data(
    screens: list[ExtractedScreen],
    sections: dict[str, list[ExtractedSection]],  # screen_name → sections
    components: dict[str, ExtractedComponent],    # name → component
    max_chars: int = 12_000,
) -> list[ChunkEnvelope]:
    """
    Gera chunks hierárquicos: Screen > Section > Component.
    Quando o conteúdo de uma Section excede max_chars, quebra por componente.
    Quando o conteúdo de um Component excede max_chars, trunca com marcador.
    """
```

### Algoritmo de chunking

```
Para cada Screen:
  chunk_screen = ChunkEnvelope(level="screen", ...)
  
  Para cada Section da Screen:
    content = section.jsx_snippet
    
    se len(content) <= max_chars:
      chunk_section = ChunkEnvelope(level="section", parent=screen, ...)
    
    senão:  # seção grande — quebra por componente
      Para cada comp_name em section.component_refs:
        comp = components[comp_name]
        content = comp.jsx_snippet[:max_chars]
        chunk_comp = ChunkEnvelope(level="component",
                                   parent=section,
                                   breadcrumb=f"{screen} > {section} > {comp_name}")
  
  se Screen não tem Sections:
    chunk_screen.content = JSX das primeiras 5 components da tela (concatenado)
```

### Formato do `context_summary`

Template por nível:
- Screen: `"Tela {name} com {n} componentes organizados em {s} seções"`
- Section: `"Seção {name} da tela {screen} — componentes: {comps}"`
- Component: `"Componente {name} (tipo: {type}) usado em: {screens}"`

### Export

```python
def export_chunks_jsonl(chunks: list[ChunkEnvelope], output_path: Path) -> None:
    """Escreve um chunk por linha em formato JSONL."""
```

### Invariantes

- `chunk_id` é único — snake_case de breadcrumb + hash de 4 chars se colisão
- `tokens_est` = `len(content) // 4` (estimativa conservadora)
- Chunks de Screen que não têm seções ficam com `content` de no máximo `max_chars`
- Nenhum chunk tem `content` vazio — chunks sem conteúdo são descartados
