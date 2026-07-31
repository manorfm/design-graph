# T29 — Concluir a integração de ChunkLevel no chunker

**Arquivo:** `src/design_graph/extraction/chunker.py`
**Depende de:** T27 (introdução do enum `ChunkLevel`)
**Status:** ✅ done

## Contexto

T27 tipou `ChunkEnvelope.level` como `ChunkLevel`, mas os 4 pontos de
construção em `chunker.py` continuaram passando strings soltas
(`level="screen"`, `level="section"`, `level="component"`) — a assinatura
mudou, o valor real nunca foi migrado. Achado ao analisar candidatos pra
próxima fase: mesma classe de problema (`ChunkEnvelope.level` era o único
dos 9 campos fechados desta rodada sem nenhum ponto de construção migrado).

## Responsabilidade

Migrar os 4 pontos de construção de `ChunkEnvelope` em `chunker.py` para
usar `ChunkLevel.SCREEN`/`.SECTION`/`.COMPONENT` em vez de string literal.

## Critério de aceite

- `isinstance(chunk.level, ChunkLevel)` para todo chunk gerado por
  `chunk_extracted_data`.
- `export_chunks_jsonl` continua serializando `level` como string plana
  (`"section"`, não `"ChunkLevel.SECTION"`) no `.jsonl` de saída — testado
  explicitamente.
- Nenhuma mudança de comportamento observável — comparações existentes
  (`chunk.level == "screen"`) continuam funcionando sem alteração.
- Suíte completa (`pytest -q`) sem regressão.
