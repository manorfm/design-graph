# Spec 01 — Módulo `parsing/`

## Responsabilidade

Transformar um arquivo HTML em dados brutos estruturados — strings de JS/CSS,
hash do arquivo, formato detectado — **sem nenhuma interpretação semântica**.
Nenhum módulo de parsing cria entidades de domínio (Component, Token, etc.).
Nenhum módulo de parsing acessa o grafo.

## Princípio central

> Parsing é leitura pura. Entrada: bytes. Saída: strings e primitivos.
> Todos os módulos aqui são funções puras ou classes sem estado mutável.

---

## 1. `source_loader.py`

### Contrato

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class RawSources:
    js: str           # JavaScript concatenado (de todos os script tags)
    css: str          # CSS concatenado (de style tags + inline styles)
    inner_html: str   # HTML interno (pode ser o HTML externo ou um bundle descomprimido)
    html_hash: str    # MD5 do arquivo HTML original (para cache incremental)
    format: str       # "bundled_react" | "tailwind" | "plain_html"

async def load(html_path: Path) -> RawSources:
    """Lê o arquivo HTML e extrai fontes JS/CSS. Async para I/O de arquivo."""
```

### Algoritmo

1. `await asyncio.to_thread(html_path.read_text)` — I/O async
2. Calcular `html_hash = md5(raw_bytes)`
3. Parsear com BeautifulSoup
4. Chamar `FormatDetector.detect(html, soup)` → `format`
5. Despachar para estratégia por formato:
   - `bundled_react`: descompactar bundles base64/gzip dos `<script>` tags
   - `tailwind` / `plain_html`: coletar `<style>` + `<script>` tags diretamente

### Estratégias de extração por formato

**bundled_react**:
```
Para cada <script> com len > 10000 e começa com "{":
  tentar json.loads()
  se bundle dict: para cada valor com campo "data":
    base64.b64decode()
    gzip.decompress() se compressed=True
    se "<!DOCTYPE" → inner_html
    senão → js_parts
```

**tailwind / plain_html**:
```
css_parts = [tag.get_text() for tag in soup.find_all("style")]
css_parts += [tag["style"] for tag in soup.find_all(style=True)]
js_parts  = [s.get_text() for s in soup.find_all("script") if s.get_text().strip()]
inner_html = html (o próprio documento)
```

### Invariantes

- `html_hash` é sempre MD5 do conteúdo original, não do processado
- `js` e `css` nunca são `None` — fallback para string vazia
- O método não lança exceção em caso de script malformado — loga no stderr e continua

---

## 2. `format_detector.py`

### Contrato

```python
def detect(html: str, soup: BeautifulSoup) -> str:
    """
    Detecta o formato do protótipo.
    Retorna: "bundled_react" | "tailwind" | "plain_html"
    """
```

### Algoritmo de detecção

```
1. Verificar scripts:
   Para cada <script>:
     se len(text) > 50000 e "compressed: true" no texto → "bundled_react"
     se len(text) > 100000 e "createElement" no texto → "bundled_react"

2. Verificar Tailwind:
   Se style_text contém pattern ".flex{", ".p-\d{", etc. → "tailwind"

3. Default → "plain_html"
```

### Invariantes

- Retorna exatamente um dos três valores — nunca `None` ou outro valor
- Não lança exceções — em caso de dúvida, retorna `"plain_html"`

---

## 3. `js_parser.py`

### Responsabilidade

Encontrar limites de funções no JavaScript e extrair o bloco `return()` de cada uma.
**Não interpreta JSX**; retorna apenas strings.

### Contrato

```python
@dataclass(frozen=True)
class FunctionBoundary:
    name: str
    start: int      # índice do "function NomeFn(" no js
    body_start: int # índice logo após o "(" da assinatura
    end: int        # índice após o "}" de fechamento da função

def find_function_boundaries(js: str, name_pattern: re.Pattern) -> list[FunctionBoundary]:
    """
    Encontra todas as funções cujo nome satisfaz name_pattern.
    Usa contagem de chaves para determinar o fim real.
    """

def find_function_end(js: str, fn_start: int) -> int:
    """
    A partir do índice de "function X(", conta chaves para achar o "}" de fechamento.
    Limite de segurança: fn_start + 120_000 chars.
    """

def extract_return_block(js: str, fn_start: int, fn_end: int) -> str:
    """
    Dentro do corpo da função (fn_start..fn_end), acha o "return (" e captura
    o conteúdo interno contando parênteses.
    Retorna string vazia se não encontrar.
    """
```

### Algoritmo de `find_function_end`

```python
def find_function_end(js: str, fn_start: int) -> int:
    i = js.find('{', fn_start)
    if i < 0 or i > fn_start + 500:   # assinatura sem corpo?
        return fn_start + 20_000
    depth = 0
    limit = min(fn_start + 120_000, len(js))
    while i < limit:
        ch = js[i]
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return limit   # fallback: atingiu o limite
```

### Algoritmo de `extract_return_block`

```python
def extract_return_block(js: str, fn_start: int, fn_end: int) -> str:
    window = js[fn_start:fn_end]
    # Procura "return (" ou "return("
    for pattern in ("return (", "return("):
        ret_idx = window.find(pattern)
        if ret_idx >= 0:
            break
    else:
        return ""
    # A partir do "(", conta parênteses
    start = window.find('(', ret_idx)
    depth, i = 0, start
    while i < len(window):
        if window[i] == '(':  depth += 1
        elif window[i] == ')':
            depth -= 1
            if depth == 0:
                return window[start + 1: i].strip()
        i += 1
    return window[start + 1:].strip()   # fallback
```

### Invariantes

- `find_function_end` **nunca** retorna um índice antes de `fn_start`
- `extract_return_block` retorna string (vazia se não encontrar) — nunca `None`
- Ambas as funções são puras e thread-safe (leitura imutável)

---

## 4. `html_parser.py`

### Responsabilidade

Análise DOM do HTML para extrair estrutura quando o formato é `plain_html`.
Detecta padrões de componentes repetidos por estrutura DOM, não por classe CSS.

### Contrato

```python
@dataclass(frozen=True)
class DOMPattern:
    signature: str          # assinatura estrutural (ex: "div>img,h3,p,button")
    count: int              # quantas vezes aparece
    first_example: str      # HTML do primeiro elemento (até 600 chars)
    inferred_name: str      # nome inferido pelo conteúdo (ex: "RestaurantCard")
    semantic_type: str      # "card" | "nav" | "modal" | etc.

def extract_dom_patterns(soup: BeautifulSoup, min_count: int = 3) -> list[DOMPattern]:
    """
    Detecta estruturas DOM que se repetem >= min_count vezes.
    Cada padrão = componente candidato em HTML puro.
    """

def extract_semantic_sections(soup: BeautifulSoup) -> list[dict]:
    """
    Usa elementos semânticos HTML5 (nav, main, aside, section, article, header, footer)
    e hierarquia de headings (h1/h2/h3) como delimitadores de seção.
    """
```

### Algoritmo de `extract_dom_patterns`

```python
def _structure_signature(tag, depth: int = 0, max_depth: int = 3) -> str:
    """Gera assinatura estrutural recursiva. Ignora texto e atributos."""
    if depth >= max_depth:
        return tag.name
    children = [c for c in tag.children if hasattr(c, 'name') and c.name]
    # Inclui até 2 classes identificadoras para distinguir variantes
    cls = tag.get('class', [])
    cls_hint = ('.' + cls[0]) if cls else ''
    base = f"{tag.name}{cls_hint}"
    if not children:
        return base
    child_sigs = ','.join(_structure_signature(c, depth + 1, max_depth) for c in children[:6])
    return f"{base}>{child_sigs}"
```

**Filtros de qualidade para ser considerado componente:**
- `len(signature) >= 15` (descarta tags simples como `<span>texto</span>`)
- `count >= min_count`
- Não é um container de layout puro (body, html, head)

### Inferência de nome a partir de estrutura

```
se contém "img" + "h3" + "p" → "Card"
se é <nav> ou contém role=navigation → "NavBar"
se contém <input> + <button> → "SearchBar"
se contém <th> ou <tr> → "DataTable"
se contém <h1> + múltiplos filhos → "PageHeader"
```

---

## 5. `token_extractor.py`

### Responsabilidade

Extrair design tokens (cores, espaçamentos, tipografia, sombras, radii, CSS vars)
do CSS+JS combinados.

### Contrato

```python
@dataclass(frozen=True)
class DesignToken:
    id: str           # hash único (ex: "col_a3f2b1c4")
    category: str     # "color" | "spacing" | "typography" | "shadow" | "radius"
    label: str        # nome semântico (ex: "primary", "space_16")
    value: str        # valor real (ex: "#ffb81c", "16px")
    usage: int        # contagem de ocorrências

def extract_tokens(sources: RawSources) -> list[DesignToken]:
    """
    Extrai todos os tokens de design de sources.css + sources.js.
    Retorna lista ordenada por categoria + uso decrescente.
    """
```

### Sub-extractors internos (não exportados)

```python
def _extract_colors(combined: str) -> list[DesignToken]: ...
def _extract_spacing(combined: str) -> list[DesignToken]: ...
def _extract_typography(combined: str) -> dict: ...
def _extract_shadows(combined: str) -> list[str]: ...
def _extract_radii(combined: str) -> list[str]: ...
def _extract_css_vars(combined: str) -> dict[str, str]: ...
```

### Invariantes

- Cores brancas/pretas puras (`#fff`, `#000`, `rgba(0,0,0,0)`) são filtradas
- Cores com menos de 2 ocorrências são filtradas (não são tokens, são one-offs)
- Espaçamentos são normalizados para múltiplos de 4px (`round(v/4)*4`)
- IDs de tokens são determinísticos (mesmo valor → mesmo ID em qualquer run)
- `usage` reflete ocorrências no combined (css + js), não apenas no CSS

---

## Diagrama de dependências do módulo `parsing/`

```
html_path (Path)
    ↓
source_loader.load()
    ├── format_detector.detect()      → "bundled_react" | "tailwind" | "plain_html"
    └── RawSources { js, css, inner_html, html_hash, format }
         ↓                              ↓
  js_parser (lê .js)         html_parser (lê .inner_html via BeautifulSoup)
  token_extractor (lê .css + .js)
```

Nenhum módulo de parsing cria dependência circular com outro.
`token_extractor` depende de `RawSources` mas não de `js_parser` nem `html_parser`.
