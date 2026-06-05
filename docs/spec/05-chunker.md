# Spec 05 — Chunker (HTML → Contexto para IA)

## Problema

Um arquivo HTML gerado por um agente pode ter centenas de kilobytes de JSX/HTML.
Injetar o arquivo inteiro no contexto de uma IA é caro e ineficaz.
O chunker resolve isso quebrando o arquivo em pedaços semanticamente coerentes,
cada um com um envelope de contexto que o torna autocontido.

## Dois sub-problemas

### 5a — Chunking estrutural

Como quebrar sem perder coerência? Um componente não pode ser cortado ao meio.
Uma seção não pode ser misturada com outra.

### 5b — Preservação de referências

Quando a IA recebe um chunk isolado, ela precisa entender onde ele se encaixa.
O envelope (`breadcrumb`, `sibling_ids`, `parent_id`) fornece esse contexto
sem incluir o conteúdo dos outros chunks.

---

## Hierarquia de chunking

```
Nível 0: Documento (o HTML inteiro)
  └── Nível 1: Screen/Tela        (ex: "RestaurantsPage")
        └── Nível 2: Section       (ex: "Header", "Filtros", "Lista")
              └── Nível 3: Component (ex: "SectionCard", "BtnPrimary")
```

A granularidade final depende do tamanho de cada nível:
- Se Screen cabe em `max_chars` → 1 chunk por Screen
- Se Section cabe em `max_chars` → 1 chunk por Section
- Se Section não cabe → 1 chunk por Component dentro da Section

---

## Envelope de um chunk

```python
@dataclass
class ChunkEnvelope:
    # Identificação
    chunk_id: str               # ex: "restaurants_page__header"
    breadcrumb: str             # ex: "RestaurantsPage > Header"
    level: str                  # "screen" | "section" | "component"

    # Navegação
    parent_id: str | None       # ex: "restaurants_page"
    sibling_ids: list[str]      # outros chunks no mesmo nível/pai
    child_ids: list[str]        # chunks filhos deste (se houver)

    # Conteúdo
    content: str                # JSX sanitizado ou HTML estruturado
    tokens_est: int             # len(content) // 4

    # Metadados
    component_refs: list[str]   # nomes de componentes referenciados
    context_summary: str        # 1 frase descritiva
    source_screen: str          # nome da Screen de origem
```

### Por que `sibling_ids` importa

Quando a IA processa o chunk "RestaurantsPage > Lista", o `sibling_ids`
(`["restaurants_page__header", "restaurants_page__filtros"]`) diz quais
outros chunks existem no mesmo pai. A IA pode pedir os irmãos se precisar
de contexto adicional, sem processar o documento inteiro.

---

## Algoritmo de geração

```python
def chunk_extracted_data(
    screens: list[ExtractedScreen],
    sections: dict[str, list[ExtractedSection]],
    components: dict[str, ExtractedComponent],
    max_chars: int = 12_000,
) -> list[ChunkEnvelope]:

    result = []

    for screen in screens:
        screen_id = _to_chunk_id(screen.name)
        screen_sections = sections.get(screen.name, [])

        if not screen_sections:
            # Tela sem seções: 1 chunk com JSX dos componentes diretos
            content = _build_screen_content(screen, components, max_chars)
            if content:
                result.append(ChunkEnvelope(
                    chunk_id=screen_id,
                    level="screen",
                    parent_id=None,
                    content=content,
                    ...
                ))
            continue

        # Tela com seções
        section_chunk_ids = [_to_chunk_id(f"{screen.name}__{s.name}") for s in screen_sections]

        for i, section in enumerate(screen_sections):
            sec_id = section_chunk_ids[i]
            siblings = [sid for j, sid in enumerate(section_chunk_ids) if j != i]

            if len(section.jsx_snippet) <= max_chars:
                # Seção pequena: 1 chunk
                result.append(ChunkEnvelope(
                    chunk_id=sec_id, level="section",
                    parent_id=screen_id,
                    sibling_ids=siblings,
                    content=section.jsx_snippet,
                    ...
                ))
            else:
                # Seção grande: quebra por componente
                comp_chunks = _chunk_section_by_components(
                    section, components, screen, sec_id, siblings, max_chars
                )
                result.extend(comp_chunks)

    return result
```

### `_to_chunk_id`

```python
def _to_chunk_id(name: str) -> str:
    """
    Converte "RestaurantsPage > Header" → "restaurants_page__header"
    Garante unicidade com hash de 4 chars em caso de colisão.
    """
    slug = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
    return slug
```

---

## Export em JSONL

```python
def export_chunks_jsonl(chunks: list[ChunkEnvelope], output_path: Path) -> None:
    """
    Escreve um chunk por linha. Cada linha é um JSON completo.
    Permite streaming e processamento linha a linha por ferramentas externas.
    """
    with output_path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(dataclasses.asdict(chunk), ensure_ascii=False) + "\n")
```

### Exemplo de chunk exportado

```json
{
  "chunk_id": "restaurants_page__header",
  "breadcrumb": "RestaurantsPage > Header",
  "level": "section",
  "parent_id": "restaurants_page",
  "sibling_ids": ["restaurants_page__lista", "restaurants_page__filtros"],
  "child_ids": [],
  "content": "<div style={{padding:'24px'}}>\n  <h1>Restaurantes</h1>\n  <BtnFilter />\n</div>",
  "tokens_est": 112,
  "component_refs": ["BtnFilter"],
  "context_summary": "Seção Header da tela RestaurantsPage — componentes: BtnFilter",
  "source_screen": "RestaurantsPage"
}
```

---

## Chunking de HTML puro (plain_html)

Para HTML sem React, o chunker usa `html_parser.extract_semantic_sections()`:

```
<nav>       → chunk "NavBar"
<header>    → chunk "PageHeader"
<main>
  <section> → chunk "MainContent__Section1"
  <section> → chunk "MainContent__Section2"
<footer>    → chunk "Footer"
```

Padrões DOM repetidos detectados por `extract_dom_patterns()` se tornam
chunks do tipo "component" com múltiplos exemplos:

```json
{
  "chunk_id": "dom_pattern__card",
  "level": "component",
  "content": "<!-- 8 instâncias detectadas -->\n<div class=\"card\">...",
  "tokens_est": 340,
  "context_summary": "Componente Card repetido 8× no documento"
}
```

---

## CLI para chunking standalone

```bash
design-graph chunk <prototype.html> [--output chunks.jsonl] [--max-chars 12000]
```

O chunker pode ser usado sem construir o grafo completo — para o caso de
"arquivo HTML gigante, quero apenas os chunks para IA".

### Entry point

```python
# design_graph/cli/build.py

def cmd_chunk(html_path: Path, output_path: Path, max_chars: int) -> None:
    """Extrai e exporta chunks sem persistir no grafo."""
    sources = asyncio.run(load(html_path))
    boundaries = find_all_boundaries(sources.js)
    screens, comps, sections = extract_all(sources, boundaries)
    chunks = chunk_extracted_data(screens, sections, comps, max_chars)
    export_chunks_jsonl(chunks, output_path)
    print(f"{len(chunks)} chunks exportados → {output_path}")
```

---

## Invariantes

- `tokens_est` nunca excede `max_chars // 4` por chunk
- `content` nunca é vazio — chunks sem conteúdo são descartados silenciosamente
- `chunk_id` contém apenas `[a-z0-9_]` — sem espaços, acentos ou caracteres especiais
- A soma de `tokens_est` de todos os chunks < total de tokens do documento
  (por causa de sanitização e overhead de envelope não contado no conteúdo)
