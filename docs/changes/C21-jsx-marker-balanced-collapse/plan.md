# Plan C21 — Colapso balanceado de expressões dinâmicas em JSX

## Objetivo

Eliminar a corrupção de marcadores `{[conditional:X]}`/`{[either:A|B]}`/
`{[list:X]}` quando o componente colapsado tem props com chaves próprias
(`color={C.red}`), e tornar determinística a sobrevivência de markup cru
(ícones/spans) condicionalmente renderizado — sem depender de contagem de
caracteres.

## Critério de aceite

```bash
pytest tests/unit/extraction/test_jsx_sanitizer.py -v
pytest tests/unit/core/test_models.py -k JsxMarker -v
pytest tests/test_architecture_guardrails.py -v   # jsx_sanitizer.py não viola G1/G2
pytest -q                                          # suíte completa sem regressão
```

## Sequência TDD

### Fase 0 — investigação

Reproduzido contra o grafo real (`ipede_manager_v15.1`, tela `ItemsPage`,
componente `ItemCard`) via `get_screen_full`/`get_full_jsx` do MCP: os dois
badges condicionais de `ItemCard` (`item.promotional`/desconto, cada um
com prop `color={...}`) saem corrompidos mesmo no "JSX completo". Raiz:
`RE_JSX_SHORT_CIRCUIT`/`RE_JSX_TERNARY_COMPONENTS`/`RE_JSX_MAP_RENDER`
usam cauda `[^}]{0,400}\}` — para na primeira `}`, que um prop aninhado
fornece cedo demais. Confirmado com um agente de pesquisa isolando a
regex e reproduzindo o exato texto corrompido observado no MCP.

### Fase 1 — RED

`tests/unit/extraction/test_jsx_sanitizer.py` (módulo novo,
`design_graph.extraction.jsx_sanitizer` — ainda não existe): falha por
`ModuleNotFoundError`. Casos cobertos antes de qualquer implementação:

- conditional/either/list com prop de chave aninhada no then-branch e no
  else-branch — nenhum marcador pode deixar sobra de JSX cru depois de si;
- either com else-branch sem componente (`: null`) — deve permanecer
  intocado, igual ao comportamento de regex-não-casa anterior;
- markup cru condicional/ternário curto — preservado (já funcionava);
- markup cru condicional/ternário **longo** (>300 chars) — antes era
  apagado para `{...}` pelo fallback genérico; deve ser preservado
  inteiro;
- expressão longa não-markup — continua sendo colapsada (a proteção é
  escopada, não uma isenção geral de limite de tamanho).

`tests/unit/core/test_models.py::TestJsxMarker` — valida o
`value object` novo (`JsxMarker`/`JsxMarkerKind`): `LIST`/`CONDITIONAL`
exigem 1 nome, `EITHER` exige exatamente 2, formato textual do `__str__`.

### Fase 2 — GREEN

- `core/models.py`: `JsxMarkerKind` (StrEnum) + `JsxMarker` (frozen
  dataclass, validação em `__post_init__`, `__str__` como única fonte do
  formato textual).
- `core/patterns.py`: substitui as 3 regex de cauda gananciosa por regex
  de cabeça (`RE_JSX_LIST_HEAD`/`RE_JSX_CONDITIONAL_HEAD`/`RE_JSX_EITHER_HEAD`)
  + 2 regex de proteção de markup cru
  (`RE_JSX_MARKUP_CONDITIONAL_HEAD`/`RE_JSX_MARKUP_EITHER_HEAD`) +
  `RE_JSX_EITHER_ELSE_BRANCH` (busca o nome do else-branch já dentro do
  span balanceado, nunca num texto não-delimitado).
- `extraction/jsx_sanitizer.py` (novo): `sanitize_jsx` movido de
  `component_extractor.py` para seu próprio módulo — responsabilidade
  isolada (sanitização para consumo por agente, distinta da extração de
  dados por componente). `_collapse_marked_regions` unifica os 3 casos via
  `find_matching_delimiter`; `_protected_markup_spans` +
  `_collapse_long_expressions` implementam a proteção de markup cru.
- `extraction/component_extractor.py`: remove a implementação antiga de
  `sanitize_jsx` e os imports que só ela usava; importa `sanitize_jsx` do
  novo módulo.

### Fase 3 — refactor / limpeza

- Testes de `sanitize_jsx` que viviam duplicados em
  `test_component_extractor.py` e
  `test_component_extractor_single_pass_guards.py` foram consolidados em
  `test_jsx_sanitizer.py` (dono único da função) — evita 3 suítes testando
  a mesma função com convenções divergentes. `child_refs`/variantes de
  componente com dígito etc. (que testam `extract_component`, não
  `sanitize_jsx`) permaneceram onde estavam.
- `mcp/tools.py`: descrição da tool `get_full_jsx` e o comentário de
  `CappedJsx.notice()` corrigidos — o nome "full unsanitized JSX" era
  impreciso mesmo antes deste fix (a função sempre devolveu o
  `jsx_snippet` já sanitizado, só sem o corte de tamanho do `CappedJsx`).

## Validação end-to-end

Suíte completa (`pytest -q`) sem regressão: 1620 passando, mesmas 5
falhas pré-existentes e não relacionadas (`ModuleNotFoundError: mcp`,
dependência ausente no venv — confirmado idêntico via `git stash`).
Guardrails de arquitetura (G1/G2) verificadas: `jsx_sanitizer.py` importa
só de `core/` e `parsing/`, nunca de `graph/`/`mcp/`.

Não foi possível revalidar contra um rebuild real do prototype original —
o arquivo-fonte de `ipede_manager_v15.1` não está neste diretório (só um
`iPede Manager v15.1.html` sem `ItemCard`, provavelmente uma versão
diferente/gitignored). A regressão de `sanitize_jsx` reproduz o texto
corrompido exato observado via MCP contra o grafo já construído, o que é
suficiente para confirmar a causa raiz e a correção — mas o usuário
precisa rodar `design-graph --force <prototype original>` para que o
grafo em uso reflita a extração corrigida.
