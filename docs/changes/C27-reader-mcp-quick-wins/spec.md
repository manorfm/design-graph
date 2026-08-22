# Spec C27 — Reader/MCP: ganhos rápidos

## Contexto

Terceira de 9 changes (C25–C33) motivada pela auditoria técnica completa do
pipeline (ver C25/spec.md). Quatro melhorias independentes na camada
reader/MCP, nenhuma exigindo mudança de schema — agrupadas por serem todas
pequenas o suficiente para caber num único change sem inflar o escopo.

## Problemas identificados

### P1 — Fuzzy match sempre faz full-scan, mesmo com nome exato

`_fuzzy_find_component`/`_fuzzy_find_screen` (`graph/reader.py`) sempre rodam
`MATCH (c:Component) RETURN c.name` completo antes de comparar em Python —
mesmo quando o nome recebido já é exato (o caso comum: um agente que acabou
de chamar `list_screens`/`list_components` e está reusando um nome já
correto). Isso é O(n) sobre todo o protótipo em cada chamada de
`get_component`, `get_component_spec`, `get_screen_full` etc.

### P2 — Camada MCP não reaproveita a validação de nome de documento do CLI

`_find_reader` (`mcp/tools.py`) e `_set_prototype` (`mcp/server.py`) comparam
o `doc`/`name` recebido do agente contra nomes de banco já enumerados do
disco, sem nenhuma validação de formato — enquanto o CLI já valida via
`GraphDocumentName` (rejeita `..`, `/`, `\`, nome vazio). Não há exploração
conhecida hoje (a comparação nunca reconstrói um `Path` a partir do valor do
agente), mas é uma inconsistência de defesa em profundidade: se a lógica de
resolução mudar no futuro, a validação do CLI não protege o MCP.

### P3 — `get_component_children` não distingue "não encontrado" de "é folha"

Mensagem única (`"'{name}' não possui filhos detectados (componente folha ou
não encontrado)."`) para dois casos bem diferentes — o agente não sabe se
deve tentar `search()` para achar o nome certo, ou se já está no componente
certo e ele simplesmente não tem filhos.

### P4 — Descrição de `get_tokens` desatualizada

O schema JSON da tool já aceita as 6 categorias de `TokenCategory` (`color,
spacing, typography, shadow, radius, css_var`) — o `enum` é gerado
dinamicamente a partir do enum Python. Só a `description` textual da tool e o
README dizem "colors and spacing", subutilizando a tool na cabeça de quem lê
antes do código.

## Solução proposta

| Task | Problema | Camada |
|---|---|---|
| T52 | P1 | `graph/reader.py` |
| T53 | P2 | `mcp/tools.py` + `mcp/server.py` |
| T54 | P3 | `graph/reader.py` + `mcp/tools.py` |
| T55 | P4 | `mcp/tools.py` + `README.md` |

**T52** — `_fuzzy_find_component`/`_fuzzy_find_screen` tentam `MATCH (...
{name:$hint}) RETURN ...name` (lookup por chave primária) antes do full-scan
atual. Só cai para o full-scan + `_fuzzy_match` quando o lookup exato não
encontra nada. Comportamento observável idêntico — muda só o custo no
caminho feliz.

**T53** — `_find_reader` (tools.py) e `_set_prototype` (server.py) validam o
`name` recebido construindo `GraphDocumentName(name)` antes de comparar
contra os readers carregados; um `ValueError` (nome malformado) é capturado
e o fluxo cai para a mesma mensagem "not found"/"não encontrado" já usada
para qualquer nome sem match — nenhuma exceção crua chega ao chamador MCP.

**T54** — novo método `GraphReader.component_exists(name)` (lookup direto
por PK). `get_component_children` (tools.py) passa a checar existência
separadamente do resultado de filhos: sem filhos E não existe → mensagem de
"não encontrado" (mesmo texto já usado em `get_component_layout_profile`,
por consistência); sem filhos MAS existe → nova mensagem "é um componente
folha".

**T55** — descrição da tool `get_tokens` (tools.py) e a seção
correspondente do README passam a listar as 6 categorias reais, e o README
ganha o parâmetro `screen?` que já existe no schema mas não estava
documentado na tabela de tools.

## Cobertura de testes exigida

- **P1/T52**: `test_exact_component_match_skips_full_scan`/`test_exact_screen_match_skips_full_scan`
  — espiona `_q` e confere exatamente 1 query quando o nome é exato.
  `test_prefix_component_match_still_falls_back` — confere que o fallback
  (2 queries: miss exato + full-scan) ainda funciona e resolve corretamente.
- **P2/T53**: `test_malformed_doc_name_falls_through_to_not_found` (tools.py,
  via `pick_reader`) e `test_set_prototype_malformed_name_falls_through_to_not_found`
  (server.py) — um nome no formato `../etc/passwd` não lança exceção, resolve
  para a mensagem padrão de "não encontrado".
- **P3/T54**: `test_get_component_children_leaf_component_message` (existe,
  sem filhos) vs `test_get_component_children_not_found_message` (não
  existe) — mensagens distintas e mutuamente exclusivas. `component_exists`
  testado diretamente no `GraphReader` real (`TestComponentExists`).
- **P4/T55**: sem teste automatizado dedicado — mudança de texto
  documentacional, verificada por leitura.

Suíte completa (`pytest tests/unit/ -q`) sem regressão e guardrails
(`pytest tests/test_architecture_guardrails.py -q`) intactas; rebuild real
contra `iPede Manager v21.2.html` (DB descartável em `/tmp`) reportado no
`plan.md`.

## Segurança

T53 é puramente defensivo (reforça uma fronteira já não-explorável hoje) —
sem mudança de comportamento para nomes válidos, e sem nova superfície de
I/O. As demais tasks não tocam segurança.

## Fora de escopo

- Reescrever `_fuzzy_match` para usar índice/cache persistente — o full-scan
  de fallback continua O(n); T52 só evita pagar esse custo no caminho feliz
  (nome exato), que é a maioria dos casos reais.
- Unificar `_find_reader`/`_set_prototype` num único helper compartilhado —
  a duplicação já existia antes deste change e não faz parte do problema
  reportado (P2 é sobre validação ausente, não sobre duplicação de código).
