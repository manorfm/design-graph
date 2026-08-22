# Plan C25 — Integridade de escrita

## Objetivo

Fechar P1–P2 de `spec.md` sem regredir nenhum change anterior, mantendo as
guardrails de arquitetura.

## Critério de aceite

```bash
pytest tests/unit/ -q
pytest tests/test_architecture_guardrails.py -q
design-graph "iPede Manager v21.2.html" --force --db /tmp/c25-rebuild.db
design-graph validate --db /tmp/c25-rebuild.db
```

Rebuild real sempre contra `/tmp` — nunca a DB de produção do repositório.

## Ordem de implementação

```
T47  graph/writer.py (GraphWriteSession)        (P1) — independente
T48  graph/writer.py (GraphWriter) +            (P2) — independente,
     core/models.py (BuildStats) +                     pode rodar em
     pipeline/coordinator.py +                          paralelo a T47
     cli/build.py
```

## Sequência por task

### T47 — Lock de arquivo em GraphWriteSession

**RED:** `test_concurrent_write_session_raises_build_lock_error` — abrir uma
`GraphWriteSession` e, ainda dentro do `with`, tentar abrir uma segunda sobre
o mesmo `final_path` → `BuildLockError`. `test_lock_released_after_session`
— depois que a primeira sessão fecha (com ou sem exceção dentro do bloco),
uma nova sessão sobre o mesmo path funciona normalmente.

**GREEN:** `GraphWriteSession.__init__` ganha `self._lock_path` (`.{name}.lock`)
e `self._lock_file`. `__enter__` chama `_acquire_lock()` antes de
`_cleanup_temp()`; qualquer exceção entre a aquisição do lock e o fim de
`__enter__` libera o lock antes de propagar. `__exit__` chama
`_release_lock()` sempre, depois de `_release_db()`.

### T48 — Contagem de erros de escrita não-duplicados

**RED:** `test_safe_execute_counts_non_duplicate_errors` — uma statement Cypher
inválida incrementa `writer._write_errors`; uma chave duplicada não
incrementa. `test_get_stats_reports_write_errors` — `get_stats()` inclui
`write_errors` igual à contagem.

**GREEN:** `GraphWriter.__init__` ganha `self._write_errors: list[str] = []`.
`_safe_execute` faz `append` (capado em 50 entradas) no branch de erro
não-duplicado, antes do `logger.warning` já existente — comportamento de log
não muda. `get_stats()` adiciona `"write_errors": len(self._write_errors)`.
`BuildStats` ganha `write_errors: int = 0`; `coordinator.py` propaga de
`raw_stats`; `cli/build.py` inclui no JSON sempre e no resumo textual só
quando `> 0`.

## Validação end-to-end

Rebuild real contra `iPede Manager v21.2.html` (DB descartável em `/tmp`),
comparado ao estado pré-C25 (mesmo arquivo, sem as mudanças deste change):

```
Métrica                          | pré-C25              | pós-T47        | pós-T48 (final)
----------------------------------|-----------------------|----------------|----------------
Build isolado (sem concorrência)  | passa                 | passa          | passa
Segunda sessão concorrente        | corrompe/indefinido   | BuildLockError | BuildLockError
write_errors em build limpo       | não existe            | não existe     | 0 (medido)
```

Rebuild real medido: `screens=14 comps=177 tokens=86 sections=64 contains=412
styles=4131 texts=1796 interactions=30 component_props=632 section_styles=521
write_errors=0`, `113.71s`.

`design-graph validate --db /tmp/c25-rebuild.db`: `status=ok errors=0
warnings=0` (14 screens, 177 components, 64 sections, 86 tokens, 412 CONTAINS).

Suíte: `pytest tests/unit/ -q` → 1648 passed. `pytest
tests/test_architecture_guardrails.py -q` → 22 passed.
