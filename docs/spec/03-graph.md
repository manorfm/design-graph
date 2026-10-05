# Spec 03 — Módulo `model/graph/`

## Responsabilidade

Definir o schema do grafo, escrever entidades extraídas no Kuzu e fornecer
uma camada de leitura tipada. Nenhum módulo de `model/graph/` faz parsing ou extração.

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

## 2. `writer.py` e `batch.py`

### Responsabilidade

Dividida em duas partes:

- **`writer.py` (domínio → linhas)**: `GraphWriter` recebe as entidades já
  extraídas e as coleta como linhas por tabela, em memória — sem tocar no
  banco. A deduplicação é feita por conjuntos de ids; um componente definido
  substitui o "shell" coletado antes com o mesmo nome.
- **`batch.py` (linhas → Kuzu)**: `write_rows()` grava cada tabela com um
  único `UNWIND $rows AS r CREATE …` por lote de linhas — nós antes de
  relações. Nomes de tabela e coluna vêm do DDL de `schema.py`
  (`node_tables()`, `rel_tables()`); qualquer outro nome é recusado, e os
  valores sempre vão como parâmetro.

### Contrato

```python
class GraphWriter:
    def __init__(self, conn: kuzu.Connection): ...

    def write_tokens(self, tokens: list[DesignToken]) -> int: ...      # tokens novos coletados
    def write_icons(self, icons: list[IconAsset]) -> int: ...
    def write_module_texts(self, texts: list[TextEntry]) -> int: ...
    def declare_screens(self, screens: list[ExtractedScreen]) -> None: ...
    def write_component(self, comp: ExtractedComponent) -> None: ...   # idempotente por nome
    def flush_pending_contains(self) -> int: ...                      # CONTAINS adiados + shells
    def write_screen(self, screen: ExtractedScreen, sections: list[ExtractedSection]) -> None: ...

    def commit(self) -> None:
        """Grava todas as linhas coletadas. Uma vez só: escrever depois disso é erro."""

    def get_stats(self) -> dict[str, int]: ...                        # contagens + write_errors
```

`GraphWriteSession` chama `commit()` ao sair sem erro; o pipeline chama
antes de `get_stats()`.

### Ordem de escrita

```
1. record_model(), write_tokens(), write_icons(), write_module_texts()
2. declare_screens()      — identidades das telas, para referências tipadas
3. write_component()      — para cada comp (Style, Interaction, UIText, ComponentProp)
4. flush_pending_contains()
5. write_screen()         — cria componentes "shell" para refs nunca extraídas
6. commit()               — nós de cada tabela, depois relações
```

### Falhas

O Kuzu desfaz um statement que falha por inteiro, então um lote que falha é
regravado linha a linha: a linha ruim vira um item em `write_errors` (até
50) e as demais são gravadas. Chave primária repetida é ignorada sem erro,
como um `CREATE` repetido seria. Uma relação cujo nó de origem ou destino
não existe não casa no `MATCH` e é descartada.

---

## 3. `reader.py`

### Responsabilidade

Camada de consulta tipada. Usada por `interface/mcp/tools.py` e `interface/cli/query.py`.
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
    def get_full_source(self, name: str) -> dict | None: ...  # componente ou, na falta, tela
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
