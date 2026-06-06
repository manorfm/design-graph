# Spec 04 — Módulo `mcp/`

## Responsabilidade

Servir o protocolo MCP (JSON-RPC 2.0 via stdio). Recebe mensagens, despacha para
as tool implementations, formata a resposta. Não faz parsing de HTML nem acessa
o grafo diretamente — usa `graph/reader.py` como única interface com o Kuzu.

---

## 1. `server.py`

### Responsabilidade única

Loop de leitura de `stdin` / escrita em `stdout`. Protocolo puro.
Não contém lógica de negócio — delega tudo para `tools.py`.

### Contrato

```python
class MCPServer:
    def __init__(self, readers: list[tuple[str, GraphReader]]):
        """
        readers: lista de (doc_name, GraphReader) — um por protótipo carregado.
        """
        self._readers = readers
        self._active_doc: str = os.environ.get("DESIGN_GRAPH_DOC", "").strip()

    def run(self) -> None:
        """Loop principal: lê stdin linha a linha, processa, escreve stdout."""

    def handle(self, msg: dict) -> dict | None:
        """Despacha mensagem para o método correto. Retorna resposta ou None."""
```

### Métodos do protocolo

| `method` | Ação |
|---|---|
| `initialize` | Retorna capabilities e lista de protótipos carregados |
| `notifications/initialized` | Ignorado (retorna None) |
| `tools/list` | Retorna `TOOLS` schema |
| `tools/call` | Despacha para `ToolDispatcher` |
| qualquer outro | Retorna error -32601 |

### Isolação de estado

`_active_doc` é estado da sessão (mutável via `set_prototype`).
É o único campo mutável do servidor. Toda outra lógica é stateless.

---

## 2. `tools.py`

### Responsabilidade

Implementar cada ferramenta MCP. Recebe um `GraphReader` e os argumentos já
validados. Retorna sempre uma `str` formatada em Markdown.

### Contrato por ferramenta

```python
class ToolDispatcher:
    def __init__(self, readers: list[tuple[str, GraphReader]]):
        self._readers = readers

    def dispatch(self, tool_name: str, args: dict, conn_doc: str | None) -> str:
        """
        Resolve o reader correto (via pick_reader) e despacha para o método.
        Retorna mensagem de erro legível se o reader não for encontrado.
        """

    def pick_reader(self, doc: str | None, active_doc: str) -> tuple[GraphReader | None, str | None]:
        """
        Resolve qual reader usar.
        Ordem: doc= arg → active_doc → auto-select se 1 protótipo → erro.
        Retorna (reader, None) no sucesso, (None, error_msg) no erro.
        """
```

### Assinaturas das ferramentas

```python
def list_screens(self) -> str: ...
def get_screen(self, reader: GraphReader, name: str) -> str: ...
def get_section(self, reader: GraphReader, screen: str, section: str) -> str: ...
def get_component(self, reader: GraphReader, name: str) -> str: ...
def get_tokens(self, reader: GraphReader, category: str | None) -> str: ...
def find_token_usage(self, reader: GraphReader, value: str) -> str: ...
def search(self, query: str) -> str: ...   # busca em TODOS os readers
def impact(self, reader: GraphReader, name: str) -> str: ...
def get_full_jsx(self, reader: GraphReader, name: str) -> str: ...
def get_component_interactions(self, reader: GraphReader, name: str) -> str: ...
def set_prototype(self, name: str) -> str: ...

# NOVO: aproveita CONTAINS
def get_component_children(self, reader: GraphReader, name: str) -> str: ...
```

### Formato de saída Markdown

Cada tool retorna Markdown puro. Padrão de cabeçalho:
```
# Tela: {name}
## Seções visuais
### {section_name}
...
```

Nenhuma tool retorna JSON diretamente — sempre Markdown para consumo por LLM.

---

## 3. `search.py`

### Responsabilidade

Busca cross-prototype com ranking de relevância. Substitui o `CONTAINS` literal
atual por uma busca com score.

### Contrato

```python
@dataclass
class SearchResult:
    type: str       # "Screen" | "Component" | "Token" | "UIText"
    name: str
    detail: str
    id: str
    doc: str
    score: int      # 100=exact, 80=prefix, 60=suffix, 40=contains, 20=alias

def search(
    readers: list[tuple[str, GraphReader]],
    query: str,
    max_results: int = 30,
) -> list[SearchResult]:
    """
    Expande query com aliases, busca em todos os readers,
    deduplicata por (doc, id), ordena por score desc.
    """
```

### Algoritmo de scoring

```python
def _score(name: str, query: str) -> int:
    n, q = name.lower(), query.lower()
    if n == q:                  return 100
    if n.startswith(q):         return 80
    if n.endswith(q):           return 60
    if q in n:                  return 40
    return 0

def _expand_query(query: str, aliases: dict) -> list[str]:
    """Retorna query + termos de aliases correspondentes, deduplicados."""
    q = query.lower().strip()
    terms = [q]
    for alias, expansions in aliases.items():
        if alias in q:
            terms.extend(e.lower() for e in expansions)
    return list(dict.fromkeys(terms))[:6]  # máximo 6 termos expandidos
```

### Deduplicação cross-prototype

Resultado com mesmo `(doc, id)` aparece apenas uma vez.
Se o mesmo componente existe em dois protótipos diferentes, aparece duas vezes
(com doc diferente) — isso é correto, pois são contextos distintos.

---

## 4. `aliases.py`

### Responsabilidade

Centralizar o mapa de aliases PT/EN separado de toda lógica.
Permite estender sem tocar em `search.py`.

### Contrato

```python
ALIASES: dict[str, list[str]] = {
    "botão":      ["Btn", "Button", "button"],
    "modal":      ["Modal", "Dialog", "Confirm", "Overlay"],
    # ... (mapa completo, igual ao atual + extensões)
}

def get_aliases() -> dict[str, list[str]]:
    """Retorna cópia do mapa — imutável para chamadores."""
    return dict(ALIASES)
```

### Extensão

Para adicionar um alias, basta editar `aliases.py`. Nenhum outro arquivo muda.

---

## Schema MCP (tool definitions)

O schema das tools fica em `tools.py` como constante `TOOL_DEFINITIONS: list[dict]`.
O `server.py` importa e expõe diretamente. Não há geração dinâmica de schema.

```python
TOOL_DEFINITIONS = [
    {
        "name": "list_screens",
        "description": "...",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    # ... cada tool com description atualizada
]
```

### Nova tool: `get_component_children`

```python
{
    "name": "get_component_children",
    "description": (
        "Retorna os componentes filhos diretos que um componente renderiza. "
        "Aproveita a relação CONTAINS do grafo para mostrar hierarquia de composição. "
        "Ex: get_component_children(name='RestaurantCard') → [Badge, StarRating, BtnOrder]"
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Nome do componente pai"},
            "doc": _doc_param(),
        },
        "required": ["name"],
    },
}
```
