# Spec 06 — Design de Concorrência

## Princípio geral

> Paralelizar leitura, serializar escrita.

A string `js` é imutável em Python — múltiplas coroutines lendo posições
diferentes são totalmente seguras. Os objetos retornados pelos extractors
são novos — sem estado compartilhado mutável. Apenas as escritas no Kuzu
são serializadas.

---

## Mapa de dependências do pipeline

```
Fase 1 (sequencial): I/O de arquivo
  load(html_path) → RawSources

Fase 2 (paralela segura): two independent reads on RawSources
  extract_tokens(sources)            ┐
  find_all_boundaries(sources.js)    ┤  asyncio.gather
  extract_screen_boundaries(...)     ┘

Fase 3 (paralela por componente): cada componente é independente
  [extract_component(js, boundary) for boundary in boundaries]
  → asyncio.gather(*tasks, sem=Semaphore(CONCURRENCY))

Fase 4 (paralela segura): seções são independentes entre screens
  [extract_sections(js, screen, boundary) for screen in screens]
  → asyncio.gather(*tasks)

Fase 5 (sequencial): write to Kuzu — single connection
  writer.write_tokens(tokens)
  for comp in components: writer.write_component(comp)
  for screen in screens: writer.write_screen(screen, sections[screen], ...)

Fase 6 (sequencial): state save, stats, diff report
```

---

## Por que Fase 3 é segura

Cada `extract_component(js, boundary, ...)` lê `js[boundary.start : boundary.end]`.
Como `FunctionBoundary` já garante que os limites não se sobrepõem (ver Spec 01),
duas coroutines nunca leem a mesma janela de `js`.

**Caso especial**: funções aninhadas. Se uma função PascalCase está definida
dentro de outra, `find_function_end` de ambas incluirá o mesmo trecho.
Isso é aceitável — resulta em dados ligeiramente sobrepostos, não em corrida.
A deduplicação acontece na inserção (guard de `_inserted_ids` no writer).

---

## Semaphore de concorrência

```python
EXTRACTION_CONCURRENCY = int(os.environ.get("DESIGN_GRAPH_CONCURRENCY", "8"))
```

Valor default 8: evita criar centenas de coroutines simultâneas para protótipos
com muitos componentes (100+). CPU-bound ops (regex) não ganham acima de
`os.cpu_count()` mas o semaphore também serve como back-pressure.

O valor pode ser ajustado via env var sem mudar código.

---

## O que NÃO paralelizar

| Operação | Motivo |
|---|---|
| `load_sources` | I/O de arquivo único — só há um arquivo |
| `find_all_boundaries` | Percorre `js` inteiro — uma única passagem |
| Fase 5 (writes Kuzu) | Kuzu não suporta múltiplas conexões de write simultâneas |
| Fase 6 (save state) | Arquivo único de estado — risco de corrida |
| `extract_tokens` + `find_boundaries` em paralelo (Fase 2) | Podem rodar em paralelo pois leem campos diferentes de `RawSources` |

---

## Dados compartilhados — análise de segurança

| Dado | Shared? | Mutável? | Risco |
|---|---|---|---|
| `RawSources.js` | Sim | Não | Nenhum — leitura pura |
| `RawSources.css` | Sim | Não | Nenhum |
| `token_map` (dict passado para extractors) | Sim | Não (build uma vez, leitura) | Nenhum |
| `INTERNALS` (set de constantes) | Sim | Não | Nenhum |
| `inserted_ids` (no writer) | Não | Sim | Sem risco — só na Fase 5 (sequencial) |
| `_active_doc` no MCP server | Não | Sim | Sem risco — thread única no servidor MCP |

---

## Implementação no coordinator

```python
# pipeline/coordinator.py

async def run_pipeline(html_path: Path, db_path: Path, state_path: Path,
                       show_diff: bool = False) -> BuildStats:

    # Fase 1: I/O
    sources = await load(html_path)

    # Fase 2: parallel reads on RawSources
    tokens_task     = asyncio.create_task(_async_extract_tokens(sources))
    boundaries_task = asyncio.create_task(_async_find_boundaries(sources.js))
    tokens, all_boundaries = await asyncio.gather(tokens_task, boundaries_task)

    # Separar screens dos components
    screen_bounds = [b for b in all_boundaries if _is_screen(b.name)]
    comp_bounds   = [b for b in all_boundaries if not _is_screen(b.name)]

    token_map = _build_token_map(tokens)

    # Fase 3: parallel component extraction
    sem = asyncio.Semaphore(EXTRACTION_CONCURRENCY)
    occurrences = Counter(b.name for b in all_boundaries)

    async def _extract_with_sem(boundary):
        async with sem:
            # asyncio.to_thread para não bloquear o event loop com regex pesado
            return await asyncio.to_thread(
                extract_component, sources.js, boundary, occurrences[boundary.name], token_map
            )

    extracted_comps = await asyncio.gather(*[_extract_with_sem(b) for b in comp_bounds])

    # Fase 4: parallel section extraction
    async def _extract_sections_for_screen(screen_boundary):
        screen = ExtractedScreen(name=screen_boundary.name, ...)
        async with sem:
            return await asyncio.to_thread(
                extract_sections, sources.js, screen, screen_boundary
            )

    all_sections_nested = await asyncio.gather(
        *[_extract_sections_for_screen(b) for b in screen_bounds]
    )

    # Fase 5: sequential write
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)
    initialize_schema(conn)
    writer = GraphWriter(conn)
    writer.write_tokens(tokens)
    for comp in extracted_comps:
        writer.write_component(comp)
    for screen_b, sections in zip(screen_bounds, all_sections_nested):
        screen = _build_screen(screen_b, extracted_comps)
        writer.write_screen(screen, sections, token_map, writer.inserted_names)

    # Fase 6: state
    save_state(state_path, _build_new_state(sources, screen_bounds, extracted_comps))
    return writer.get_stats()
```

### Por que `asyncio.to_thread`

Regex em Python é CPU-bound, não I/O-bound. `asyncio.to_thread` move a operação
para um thread pool, permitindo que outras coroutines continuem enquanto o regex
roda. Sem isso, `asyncio.gather` não daria ganho real de performance.

---

## Guardrails de concorrência

### Guardrail 1: Semaphore obrigatório

O semaphore é injetado no `coordinator.py` — não é opcional e não pode ser
bypassado pelos extractors. Os extractors não sabem que são async.

### Guardrail 2: Fase 5 nunca é async

`GraphWriter` não tem métodos `async`. Chamar `await writer.write_component()`
seria erro de tipo. Isso força a serialização na escrita.

### Guardrail 3: Extractors são funções puras (testáveis sync)

`extract_component`, `extract_sections`, etc. são funções síncronas regulares.
O `coordinator.py` as wrapa em `asyncio.to_thread`. Isso significa que todos
os testes unitários dos extractors rodam de forma síncrona normal — sem fixtures
de event loop.

### Guardrail 4: Token map é imutável após build

```python
token_map = _build_token_map(tokens)  # dict, build uma vez
# Depois disso, token_map nunca é modificado.
# Passado como argumento de leitura para todos os extractors.
```

---

## Limitações conhecidas

- `asyncio.to_thread` usa o ThreadPoolExecutor padrão do Python (default: min(32, cpu+4)).
  Para protótipos com 500+ componentes, considerar `ThreadPoolExecutor(max_workers=cpu_count)`.
- Kuzu v0.6 não suporta WAL async — writes sequenciais são a única opção.
- Se o HTML tem funções aninhadas (componente dentro de componente), os snippets
  incluirão código duplicado. Isso é cosmético — os dados do grafo ficam corretos
  porque a deduplicação garante apenas uma entrada por nome.
