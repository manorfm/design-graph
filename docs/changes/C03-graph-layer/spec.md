# Spec 03 — Módulo `graph/`

## Responsabilidade

Definir o schema do grafo, escrever entidades extraídas no Kuzu e fornecer
uma camada de leitura tipada. Nenhum módulo de `graph/` faz parsing ou extração.

## Princípio central

> O grafo é append-only durante o build (rebuild completo a cada run).
> O módulo reader é read-only. Kuzu não suporta múltiplas conexões de escrita
> simultâneas — a escrita é sempre sequencial, mesmo quando a extração foi paralela.

---

## 1. `schema.py`

### Schema completo (DDL Kuzu)

```python
SCHEMA: list[str] = [
    # ── Nós ──
    "CREATE NODE TABLE Screen("
    "  name STRING,"
    "  component_count INT64,"
    "  sections_count INT64,"
    "  PRIMARY KEY(name)"
    ")",

    "CREATE NODE TABLE Section("
    "  id STRING,"
    "  screen STRING,"
    "  name STRING,"
    "  styles_json STRING,"
    "  components_json STRING,"
    "  texts_json STRING,"
    "  jsx_snippet STRING,"
    "  detection_method STRING,"  # NOVO: "comment"|"structural"|"semantic"
    "  PRIMARY KEY(id)"
    ")",

    "CREATE NODE TABLE Component("
    "  name STRING,"
    "  comp_type STRING,"
    "  jsx_snippet STRING,"
    "  occurrence INT64,"
    "  classes STRING,"
    "  PRIMARY KEY(name)"
    ")",

    "CREATE NODE TABLE Token("
    "  id STRING,"
    "  category STRING,"
    "  label STRING,"
    "  value STRING,"
    "  usage INT64,"
    "  PRIMARY KEY(id)"
    ")",

    "CREATE NODE TABLE UIText("
    "  id STRING,"
    "  content STRING,"
    "  text_type STRING,"
    "  source STRING,"
    "  element STRING,"
    "  PRIMARY KEY(id)"
    ")",

    "CREATE NODE TABLE Style("
    "  id STRING,"
    "  element STRING,"
    "  state STRING,"
    "  property STRING,"
    "  value STRING,"
    "  PRIMARY KEY(id)"
    ")",

    "CREATE NODE TABLE Interaction("
    "  id STRING,"
    "  trigger STRING,"
    "  css_prop STRING,"
    "  from_val STRING,"
    "  to_val STRING,"
    "  transition STRING,"
    "  PRIMARY KEY(id)"
    ")",

    # ── Arestas existentes ──
    "CREATE REL TABLE USES_COMPONENT(FROM Screen TO Component)",
    "CREATE REL TABLE HAS_SECTION(FROM Screen TO Section)",
    "CREATE REL TABLE SECTION_USES(FROM Section TO Component)",
    "CREATE REL TABLE HAS_STYLE(FROM Component TO Style)",
    "CREATE REL TABLE USES_TOKEN(FROM Component TO Token)",
    "CREATE REL TABLE COMP_HAS_TEXT(FROM Component TO UIText)",
    "CREATE REL TABLE SCREEN_HAS_TEXT(FROM Screen TO UIText)",
    "CREATE REL TABLE HAS_INTERACTION(FROM Component TO Interaction)",

    # ── NOVA aresta: hierarquia de composição ──
    "CREATE REL TABLE CONTAINS("
    "  FROM Component TO Component,"
    "  weight INT64"         # número de vezes que filho aparece no JSX do pai
    ")",
]
```

### Função de inicialização

```python
def initialize_schema(conn: kuzu.Connection) -> None:
    """
    Cria todas as tabelas. Ignora erros de "table already exists"
    (necessário para o caso de rebuild parcial).
    """
    for stmt in SCHEMA:
        try:
            conn.execute(stmt)
        except Exception:
            pass  # tabela já existe
```

### Queries de stats

```python
STATS_QUERIES: dict[str, str] = {
    "screens":      "MATCH (n:Screen) RETURN count(n)",
    "components":   "MATCH (n:Component) RETURN count(n)",
    "tokens":       "MATCH (n:Token) RETURN count(n)",
    "texts":        "MATCH (n:UIText) RETURN count(n)",
    "styles":       "MATCH (n:Style) RETURN count(n)",
    "sections":     "MATCH (n:Section) RETURN count(n)",
    "interactions": "MATCH (n:Interaction) RETURN count(n)",
    "contains":     "MATCH ()-[r:CONTAINS]->() RETURN count(r)",
}
```

---

## 2. `writer.py`

### Responsabilidade

Inserir entidades extraídas no grafo. Opera de forma sequencial (requisito Kuzu).
Recebe as listas já totalmente extraídas — sem chamadas de retorno para extração.

### Contrato

```python
class GraphWriter:
    def __init__(self, conn: kuzu.Connection):
        self._conn = conn
        self._inserted_ids: set[str] = set()   # guard contra duplicatas

    def write_tokens(self, tokens: list[DesignToken]) -> int:
        """Retorna número de tokens inseridos."""

    def write_component(self, comp: ExtractedComponent) -> None:
        """
        Insere Component + Styles + Interactions + Texts + CONTAINS rels.
        Idempotente: se o componente já foi inserido (mesmo nome), ignora.
        """

    def write_screen(
        self,
        screen: ExtractedScreen,
        sections: list[ExtractedSection],
        token_map: dict[str, list[DesignToken]],
        inserted_comps: set[str],
    ) -> None:
        """
        Insere Screen + USES_COMPONENT rels + Sections + SECTION_USES rels.
        Cria componentes "shell" para referências não previamente inseridas.
        """

    def get_stats(self) -> dict[str, int]:
        """Retorna contagem de cada tipo de nó e da relação CONTAINS."""
```

### Ordem de escrita

A ordem importa por causa das foreign-key-like constraints no Kuzu:

```
1. write_tokens()         — sem dependências
2. write_component()      — para cada comp (pode criar Style, Interaction, UIText)
   └── após: criar CONTAINS entre comps já inseridos
3. write_screen()         — depende de componentes já existirem
   └── cria componentes "shell" para refs que não foram detectados como função
4. commit stats
```

### Guard de idempotência

```python
def _safe_execute(self, cypher: str, params: dict = None) -> bool:
    """
    Executa o cypher. Retorna True se sucesso, False se exceção.
    Não propaga exceções — apenas loga no stderr.
    """
    try:
        self._conn.execute(cypher, params or {})
        return True
    except Exception as e:
        sys.stderr.write(f"[writer] SKIP: {e!r}\n")
        return False
```

### Inserção de relação CONTAINS

```python
def _write_contains(self, parent: str, child: str, weight: int = 1) -> None:
    """
    Cria relação CONTAINS somente se pai e filho existem no grafo.
    Usa MATCH antes do CREATE para não gerar erro de nó não encontrado.
    """
    self._safe_execute(
        "MATCH (p:Component {name:$p}),(c:Component {name:$c}) "
        "CREATE (p)-[:CONTAINS {weight:$w}]->(c)",
        {"p": parent, "c": child, "w": weight}
    )
```

---

## 3. `reader.py`

### Responsabilidade

Camada de consulta tipada. Usada por `mcp/tools.py` e `cli/query.py`.
Read-only. Nunca recebe uma `kuzu.Connection` de write.

### Contrato

```python
class GraphReader:
    def __init__(self, conn: kuzu.Connection):
        self._conn = conn

    def list_screens(self) -> list[dict]: ...
    def get_screen(self, name: str) -> dict | None: ...
    def get_component(self, name: str) -> dict | None: ...
    def get_section(self, screen: str, section_hint: str) -> dict | None: ...
    def get_tokens(self, category: str | None = None) -> list[dict]: ...
    def find_token_usage(self, value: str) -> list[dict]: ...
    def get_interactions(self, comp_name: str) -> list[dict]: ...
    def get_full_jsx(self, name: str) -> str: ...
    def get_impact(self, name: str) -> dict: ...
    def count_nodes(self) -> dict[str, int]: ...

    # NOVO: queries que aproveitam CONTAINS
    def get_component_children(self, name: str, depth: int = 1) -> list[str]: ...
    def get_component_parents(self, name: str) -> list[str]: ...
    def find_screens_using_comp_transitively(self, name: str) -> list[str]: ...
```

### Fuzzy lookup interno

```python
def _fuzzy_find_screen(self, hint: str) -> str | None:
    """Exact → prefix → contains. Retorna None se não encontrar."""

def _fuzzy_find_component(self, hint: str) -> str | None:
    """Exact → prefix → suffix → contains. Retorna None se não encontrar."""
```

### Queries que aproveitam CONTAINS (novas)

```cypher
-- Filhos diretos de um componente
MATCH (p:Component {name:$name})-[:CONTAINS]->(c:Component)
RETURN c.name, c.comp_type ORDER BY c.name

-- Telas que usam Badge em qualquer nível de composição (até 3 níveis)
MATCH (s:Screen)-[:USES_COMPONENT*1..3]->(c:Component {name:$name})
RETURN DISTINCT s.name ORDER BY s.name

-- Componentes que contêm outros componentes (não são folhas)
MATCH (p:Component)-[:CONTAINS]->()
RETURN DISTINCT p.name, p.comp_type
```

---

## 4. `diff.py`

### Responsabilidade

Gerenciar estado incremental do build para detectar mudanças e pular builds
desnecessários.

### Contrato

```python
@dataclass
class BuildState:
    html_hash: str
    last_build: str          # ISO datetime
    screens: dict[str, str]  # name → hash
    components: dict[str, int]  # name → occurrence count

@dataclass
class BuildDiff:
    is_first_build: bool
    screens_added: list[str]
    screens_removed: list[str]
    comps_added: list[str]
    comps_removed: list[str]

def load_state(state_path: Path) -> BuildState: ...
def save_state(state_path: Path, state: BuildState) -> None: ...
def compute_diff(prev: BuildState, screens: list[ExtractedScreen],
                 comps: Counter) -> BuildDiff: ...
def compute_screen_hash(screen: ExtractedScreen) -> str: ...
```

### Invariantes

- `html_hash` nunca é None — string vazia se primeiro build
- `save_state` cria o diretório pai se não existir
- `compute_diff` é pura — não lê arquivos, apenas compara dicts
