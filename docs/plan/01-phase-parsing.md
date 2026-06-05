# Plan 01 — Fase 1: Parsing

## Objetivo

Extrair toda a lógica de leitura e parsing de HTML/JS/CSS para módulos com
responsabilidade única. O resultado: funções puras, testáveis sem arquivo real,
sem side-effects.

## Entregáveis

```
src/design_graph/core/
  __init__.py
  models.py        ← dataclasses de domínio
  patterns.py      ← todos os RE_* centralizados
  constants.py     ← INTERNALS, COLOR_LABELS, SEMANTIC_KEYWORDS

src/design_graph/parsing/
  __init__.py
  source_loader.py
  format_detector.py
  js_parser.py
  html_parser.py
  token_extractor.py

tests/unit/parsing/
  __init__.py
  test_source_loader.py
  test_format_detector.py
  test_js_parser.py
  test_html_parser.py
  test_token_extractor.py
```

## Sequência TDD

Para cada módulo, a ordem é:
1. Escrever os testes (RED)
2. Implementar a função mínima (GREEN)
3. Refatorar sem quebrar (REFACTOR)

### 1.1 `core/models.py`

Sem lógica — apenas dataclasses. Teste trivial: instanciar e verificar campos.
Mas os modelos estabelecem o contrato de dados para toda a fase 2+.

**Modelos a definir nesta fase:**
- `RawSources(frozen=True)`
- `FunctionBoundary(frozen=True)`
- `DesignToken(frozen=True)`
- `StyleEntry`, `InteractionEntry`, `TextEntry` (para Fase 2)

### 1.2 `core/patterns.py`

Mover todos os `RE_*` de `build_graph.py` para cá.
Testes verificam que os patterns compilam e casam com exemplos conhecidos.

### 1.3 `format_detector.py`

Testes:
- HTML com bundle JSON comprimido → `"bundled_react"`
- HTML com classes Tailwind → `"tailwind"`
- HTML puro → `"plain_html"`
- HTML inválido/vazio → `"plain_html"` (sem exceção)

### 1.4 `js_parser.py`

Este é o módulo mais crítico. Testes incluem:
- Função simples → limites corretos
- Função com chaves aninhadas (object literals) → não fecha prematuramente
- Função sem `return (` → `extract_return_block` retorna `""`
- Função que excede 120000 chars → cai no fallback (não explode)
- Regex `RE_SCREEN_NAME` distingue `RestaurantsPage` de `useRestaurants`

### 1.5 `token_extractor.py`

Testes:
- Cor aparece 3× → token com usage=3
- Cor com 1 ocorrência → não vira token
- Espaçamento 14px → normalizado para 16px
- CSS vars extraídas corretamente
- `#fff` e `#000` não viram tokens (filtro de preto/branco)

## Critério de aceite

```bash
pytest tests/unit/parsing/ -v   # 100% verde
pytest tests/unit/parsing/ --cov=src/design_graph/parsing --cov-report=term
# cobertura >= 90% em cada módulo
```

## Guardrails desta fase

1. Nenhum módulo de `parsing/` importa de `extraction/`, `graph/` ou `mcp/`
2. Nenhuma função em `parsing/` modifica seus argumentos
3. `source_loader.py` é o único com I/O de arquivo — tudo o mais opera em strings
4. Todos os `RE_*` ficam em `patterns.py` — nenhum regex inline em outros módulos

## Verificação de regressão

Após implementar `source_loader` + `js_parser`, rodar o teste de integração
existente `test_build.py::TestLoadSources` com os novos módulos.
O resultado deve ser idêntico ao legado para `simple.html`.
