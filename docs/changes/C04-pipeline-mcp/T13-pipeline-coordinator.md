# T13 — PipelineCoordinator

**Fase**: 4 — Pipeline
**Arquivo**: `src/design_graph/pipeline/coordinator.py`
**Depende de**: T01-T12 (todas as fases anteriores)
**Bloqueia**: CLI build command (T16-side), nada mais

---

## Responsabilidade

Orquestrar as 6 fases do pipeline de forma assíncrona, respeitando as
dependências entre fases e a serialização obrigatória das escritas.
É o único arquivo que "sabe" a ordem das operações. Todos os outros módulos
são agnósticos à orquestração.

---

## Contrato

```python
@dataclass
class BuildStats:
    screens: int
    components: int
    tokens: int
    sections: int
    interactions: int
    styles: int
    texts: int
    contains_rels: int
    duration_seconds: float

async def run_pipeline(
    html_path: Path,
    db_path: Path,
    state_path: Path,
    show_diff: bool = False,
    force: bool = False,
    concurrency: int = EXTRACTION_CONCURRENCY,
) -> BuildStats | None:
    """
    Executa o pipeline completo.
    Retorna None se o build foi pulado (html não mudou e não force=True).
    """
```

---

## TDD

```python
# tests/integration/test_pipeline.py

FIXTURE = Path(__file__).parent.parent / "fixtures" / "simple.html"


class TestRunPipeline:
    def test_creates_db(self, tmp_path):
        db_path = tmp_path / "out.db"
        state_path = tmp_path / ".state.json"
        stats = asyncio.run(run_pipeline(FIXTURE, db_path, state_path))
        assert db_path.exists()
        assert stats is not None

    def test_skips_unchanged_file(self, tmp_path):
        db_path = tmp_path / "out.db"
        state_path = tmp_path / ".state.json"
        asyncio.run(run_pipeline(FIXTURE, db_path, state_path))
        stats2 = asyncio.run(run_pipeline(FIXTURE, db_path, state_path))
        assert stats2 is None  # pulado

    def test_force_rebuilds(self, tmp_path):
        db_path = tmp_path / "out.db"
        state_path = tmp_path / ".state.json"
        asyncio.run(run_pipeline(FIXTURE, db_path, state_path))
        stats2 = asyncio.run(run_pipeline(FIXTURE, db_path, state_path, force=True))
        assert stats2 is not None  # não pulado

    def test_finds_screens(self, tmp_path):
        import kuzu
        db_path = tmp_path / "out.db"
        asyncio.run(run_pipeline(FIXTURE, db_path, tmp_path / ".state.json"))
        db = kuzu.Database(str(db_path), read_only=True)
        conn = kuzu.Connection(db)
        result = conn.execute("MATCH (s:Screen) RETURN count(s)")
        assert result.get_next()[0] >= 1

    def test_finds_components(self, tmp_path):
        import kuzu
        db_path = tmp_path / "out.db"
        asyncio.run(run_pipeline(FIXTURE, db_path, tmp_path / ".state.json"))
        db = kuzu.Database(str(db_path), read_only=True)
        conn = kuzu.Connection(db)
        result = conn.execute("MATCH (c:Component) RETURN count(c)")
        assert result.get_next()[0] >= 1

    def test_stats_all_fields_populated(self, tmp_path):
        db_path = tmp_path / "out.db"
        stats = asyncio.run(run_pipeline(FIXTURE, db_path, tmp_path / ".state.json"))
        assert stats.screens >= 0
        assert stats.components >= 0
        assert stats.duration_seconds > 0

    def test_state_saved_after_build(self, tmp_path):
        state_path = tmp_path / ".state.json"
        asyncio.run(run_pipeline(FIXTURE, tmp_path / "out.db", state_path))
        assert state_path.exists()
        state = load_state(state_path)
        assert state.html_hash != ""

    def test_results_equivalent_to_legacy(self, tmp_path):
        """
        O novo pipeline deve produzir pelo menos os mesmos componentes e telas
        que o legado build_graph.build() para simple.html.
        """
        import kuzu
        from build_graph import build as legacy_build

        # Legacy
        legacy_db = tmp_path / "legacy.db"
        legacy_build(FIXTURE, legacy_db)
        legacy_kuzu = kuzu.Database(str(legacy_db), read_only=True)
        legacy_conn = kuzu.Connection(legacy_kuzu)
        legacy_screens = set()
        r = legacy_conn.execute("MATCH (s:Screen) RETURN s.name")
        while r.has_next():
            legacy_screens.add(r.get_next()[0])

        # New
        new_db = tmp_path / "new.db"
        asyncio.run(run_pipeline(FIXTURE, new_db, tmp_path / ".state.json"))
        new_kuzu = kuzu.Database(str(new_db), read_only=True)
        new_conn = kuzu.Connection(new_kuzu)
        new_screens = set()
        r = new_conn.execute("MATCH (s:Screen) RETURN s.name")
        while r.has_next():
            new_screens.add(r.get_next()[0])

        # Novo pode ter mais (melhorias), mas nunca menos
        assert legacy_screens.issubset(new_screens)
```

---

## Estrutura interna do coordinator

```python
# pipeline/coordinator.py

import asyncio
import time
from collections import Counter
from pathlib import Path

from design_graph.parsing.source_loader import load
from design_graph.parsing.js_parser import find_all_boundaries
from design_graph.parsing.token_extractor import extract_tokens, build_token_map
from design_graph.extraction.component_extractor import extract_component, is_screen_name
from design_graph.extraction.screen_extractor import extract_screens, is_screen
from design_graph.extraction.section_extractor import extract_sections
from design_graph.graph.schema import initialize_schema
from design_graph.graph.writer import GraphWriter
from design_graph.graph.diff import load_state, save_state, compute_diff, BuildState
from design_graph.pipeline.state import build_new_state

EXTRACTION_CONCURRENCY = int(os.environ.get("DESIGN_GRAPH_CONCURRENCY", "8"))


async def run_pipeline(html_path, db_path, state_path,
                       show_diff=False, force=False, concurrency=EXTRACTION_CONCURRENCY):
    t_start = time.monotonic()

    # Fase 1: I/O
    sources = await load(html_path)

    # Cache check
    prev_state = load_state(state_path)
    if not force and prev_state.html_hash == sources.html_hash:
        return None

    # Fase 2: Parallel reads
    tokens_task = asyncio.create_task(
        asyncio.to_thread(extract_tokens, sources)
    )
    bounds_task = asyncio.create_task(
        asyncio.to_thread(find_all_boundaries, sources.js)
    )
    tokens, all_bounds = await asyncio.gather(tokens_task, bounds_task)

    token_map = build_token_map(tokens)
    screen_bounds = [b for b in all_bounds if is_screen(b.name)]
    comp_bounds   = [b for b in all_bounds if not is_screen(b.name)]
    occurrences   = Counter(b.name for b in all_bounds)

    # Fase 3: Parallel component extraction
    sem = asyncio.Semaphore(concurrency)

    async def _extract_comp(boundary):
        async with sem:
            return await asyncio.to_thread(
                extract_component, sources.js, boundary,
                occurrences[boundary.name], token_map
            )

    extracted_comps = list(await asyncio.gather(*[_extract_comp(b) for b in comp_bounds]))

    # Fase 4: Parallel section extraction
    screens = extract_screens(sources.js, screen_bounds + comp_bounds)
    screen_bound_map = {b.name: b for b in screen_bounds}

    async def _extract_sections_for(screen):
        boundary = screen_bound_map.get(screen.name)
        if not boundary:
            return screen.name, []
        async with sem:
            secs = await asyncio.to_thread(
                extract_sections, sources.js, screen, boundary
            )
            return screen.name, secs

    section_pairs = await asyncio.gather(*[_extract_sections_for(s) for s in screens])
    sections_map = dict(section_pairs)

    # Actualizar sections_count
    for screen in screens:
        screen.sections_count = len(sections_map.get(screen.name, []))

    # Fase 5: Sequential write
    _rebuild_db(db_path)
    import kuzu
    db   = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)
    initialize_schema(conn)
    writer = GraphWriter(conn)
    writer.write_tokens(tokens)
    for comp in extracted_comps:
        writer.write_component(comp, token_map)
    for screen in screens:
        writer.write_screen(screen, sections_map.get(screen.name, []), token_map)

    # Fase 6: State + stats
    stats_raw = writer.get_stats()
    save_state(state_path, build_new_state(sources, screens, extracted_comps, occurrences))

    return BuildStats(
        **stats_raw,
        duration_seconds=time.monotonic() - t_start,
    )
```

---

## Guardrails

1. `_rebuild_db` deleta o banco antigo antes de criar o novo — evita schema conflict
2. Fase 5 nunca é chamada com `asyncio.gather` — linha única, sequencial
3. O semaphore é criado dentro de `run_pipeline`, não como global — evita estado entre chamadas
4. `run_pipeline` retorna `None` explicitamente quando pula (facilita testes)

---

## Done when

- [x] `test_results_equivalent_to_legacy` passa — novo não perde screens/comps do legado
- [x] `test_creates_db` passa com a fixture `simple.html` existente
- [x] Build de `simple.html` completa em < 10s (perf check)
