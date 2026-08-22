# Spec C31 — Expansão da API MCP (get_component_full, paginação, get_build_diff)

## Contexto

Sétima de 9 changes (C25–C33) motivada pela auditoria técnica completa do
pipeline (ver C25/spec.md). Três lacunas de API independentes, todas
mapeando diretamente para o caso de uso central do produto: um agente
construindo ou evoluindo uma tela via MCP. Depende de C30 (`order_index`) —
`get_component_full` nasce já ordenado.

## Problemas identificados

### P1 — Reconstruir um componente complexo isolado exige N chamadas em cascata

Só existiam `get_component_children` (1 hop direto) e `get_component_spec`
(não-recursivo). Reconstruir um componente com vários níveis de filhos
exigia o agente chamar `get_component_children` repetidamente, subindo
nível por nível — exatamente o overhead de round-trip que o projeto existe
para evitar.

### P2 — `list_components` não pagina, ao contrário de quase toda outra tool

`search`, `get_screen_full` e `get_component_spec` já truncam com
`_truncation_notice`/`CappedJsx`. `list_components` (`graph/reader.py` +
`mcp/tools.py`) devolvia a tabela inteira sempre — num protótipo com
centenas de componentes, a resposta MCP crescia sem limite, contrariando o
objetivo central do produto (reduzir tokens no contexto do agente).

### P3 — Nenhuma forma de perguntar "o que mudou desde a última consulta"

`design-graph ... --diff` já calcula um `BuildDiff` (telas/componentes
adicionados/removidos) — mas só via CLI, e o resultado nunca era
persistido: `_log_diff` apenas imprimia e descartava. Um agente MCP não
tinha como fazer essa pergunta.

## Solução proposta

| Task | Problema | Camada |
|---|---|---|
| T67 | P1 | `graph/reader.py` + `mcp/tools.py` (`get_component_full`) |
| T68 | P2 | `mcp/tools.py` (`list_components`) |
| T69 | P3 | `core/models.py` + `pipeline/state.py` + `pipeline/coordinator.py` + `graph/reader.py` + `mcp/server.py` + `mcp/tools.py` (`get_build_diff`) |

**T67** — novo `GraphReader.get_component_full(name)`: resolve o componente
raiz (fuzzy match), coleta todo descendente via `-[:CONTAINS*1..3]->` (3
níveis, mesma profundidade já usada em todo o arquivo para fechamentos de
tela — teto literal que Kuzu exige), depois faz uma única rodada de queries
`UNWIND $names` para estilos/tokens/textos/interações/props/filhos de todo
o conjunto — mesmo padrão de junção já usado por `get_screen_full`, mas
sem duplicar sua implementação (métodos com propósitos diferentes o
suficiente para não compartilhar código, seguindo a mesma tolerância a
duplicação que `get_component`/`get_component_spec` já têm entre si).
Filhos de cada componente já saem ordenados por `order_index` (depende de
C30). Nova tool MCP `get_component_full` renderiza a árvore inteira em
Markdown, reaproveitando os mesmos helpers de truncamento
(`CappedJsx`, `_truncation_notice`, `_truncated_fields_notice`,
`StyleExtractionGap`) já usados por `get_component_spec`.

**T68** — `list_components` (tools.py) passa a mostrar no máximo
`_DEFAULT_LIST_COMPONENTS_LIMIT = 100` linhas por padrão (já ordenadas por
ocorrência DESC — o corte pega os componentes mais usados, não um recorte
arbitrário), com `_truncation_notice` + sugestão de usar `limit=` ou
`comp_type=`. Novo parâmetro opcional `limit` no schema da tool.
**Decisão de escopo**: a paginação acontece inteiramente em Python
(`comps[:limit]`, mesmo padrão que `search()` já usa com `results[:30]`),
não via `LIMIT`/`SKIP` na Cypher — o objetivo real é reduzir tokens na
resposta MCP, não custo de query (buscar algumas centenas de linhas do
Kuzu é desprezível); fazer a paginação em memória evita duplicar a query
com/sem filtro e mantém `reader.list_components()` com a mesma assinatura
que o resto do código-base (incluindo `cli/report.py`, que precisa da
lista completa) já depende.

**T69** — `compute_diff` passa a rodar **sempre** no fim de um build (não
só quando `--diff`/`show_diff` é passado) — `_log_diff` continua condicional
a `show_diff`, só o cálculo deixou de ser condicional. `BuildState` ganha
`last_diff: BuildDiff | None`; `pipeline/state.py` serializa/desserializa
esse campo (com fallback para `None` em payload malformado ou arquivo
legado sem o campo — nunca lança). `GraphReader` ganha um `state_path`
opcional no construtor (só a MCP server o preenche, apontando para
`<db>.state.json`, mesmo nome que `GraphDatabase.state_path`/
`BuildStateRepository.path` já usam) e um novo método `get_build_diff()`
que lê só esse campo do JSON — implementação própria, não reaproveita
`pipeline.state.load_build_state` para não introduzir uma dependência
`graph/ → pipeline/` que inverteria a camada estabelecida (`pipeline`
orquestra `graph`, não o contrário). Nova tool MCP `get_build_diff`.

## Cobertura de testes exigida

- **P1/T67**: `TestGetComponentFull` (reader, 5 casos: não encontrado,
  inclui raiz+descendentes, ordem de filhos, estilos por componente, fuzzy
  match) + `TestGetComponentFullTool` (tool, 4 casos, incluindo que um
  descendente de 2º nível aparece na saída, não só filhos diretos).
- **P2/T68**: `TestListComponentsPagination` (5 casos: corte no default,
  aviso de truncamento, `limit` explícito sobrepõe o default, `limit` maior
  que o total não gera aviso espúrio, ordem por ocorrência preservada no
  corte).
- **P3/T69**: `TestGetBuildDiff` (reader, 5 casos incluindo JSON malformado
  e state.json sem o campo) + `TestGetBuildDiffTool` (tool, 4 casos) +
  testes de round-trip em `pipeline/state.py` (`last_diff` sobrevive
  save/load; `None` sobrevive; arquivo legado sem a chave carrega como
  `None`) + `build_new_state(diff=...)`.

Suíte completa (`pytest tests/unit/ -q`, `pytest tests/integration/ -q`) sem
regressão e guardrails (`pytest tests/test_architecture_guardrails.py -q`)
intactas; rebuild real contra `iPede Manager v21.2.html` (DB descartável em
`/tmp`) reportado no `plan.md`.

## Segurança

Nenhuma fronteira nova de I/O além da já existente (`.state.json` já era
lido/escrito pelo pipeline; `get_build_diff` só lê um campo a mais do mesmo
arquivo). `get_component_full` não introduz interpolação de string nova em
Cypher — a profundidade `*1..3` é um literal fixo no código-fonte, nunca
recebida de um agente (nenhum parâmetro de profundidade é exposto na tool).

## Fora de escopo

- Parâmetro de profundidade configurável em `get_component_full` — manter
  fixo em 3 (mesmo valor já usado em todo o arquivo) evita qualquer
  interpolação de valor externo no comprimento do padrão Cypher; sem
  evidência de que 3 níveis seja insuficiente na prática.
- `LIMIT`/`SKIP` reais na Cypher de `list_components` — ver decisão de
  escopo em T68; o problema relatado é tamanho de resposta MCP, não custo
  de query.
- Diff de conteúdo (estilos/props mudados dentro de um componente que já
  existia) — `compute_diff`/`BuildDiff` só modelam adição/remoção de telas
  e componentes por nome, o mesmo que já existia no CLI; expandir o modelo
  de diff é uma mudança maior, sem pedido explícito no achado original da
  auditoria (E3 pedia "expor via MCP", não "enriquecer o que é comparado").
