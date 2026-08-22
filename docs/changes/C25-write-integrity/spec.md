# Spec C25 — Integridade de escrita (lock de build + erros de escrita visíveis)

## Contexto

Primeira de uma sequência de 9 changes (C25–C33) motivada por uma auditoria técnica
completa do pipeline (docs/changes/README.md ainda não lista C23/C24 — fora de
escopo aqui). A auditoria encontrou dois problemas de integridade em
`graph/writer.py` sem relação com extração/schema, por isso tratados primeiro e
isoladamente.

## Problemas identificados

### P1 — Builds concorrentes do mesmo `.db` sem lock de arquivo

`GraphWriteSession` (`writer.py:54-122`) sempre escreve no mesmo caminho fixo
`.{name}.building` antes de mover para o destino final. Não existe nenhum lock
de processo no projeto (`grep -r "flock\|fcntl" src/design_graph/` → vazio). O
repositório já inclui `watch_prototype.sh` (rebuild automático por mudança de
arquivo), que pode rodar concorrente a um build manual do mesmo prototype — os
dois processos colidiriam no mesmo diretório temporário: um pode apagar o
`.building` do outro em `_cleanup_temp()`, ou os dois podem escrever no mesmo
banco Kuzu ao mesmo tempo. Hoje isso falha de forma imprevisível (exceção Kuzu
não descritiva, ou pior, uma build "vencedora" descartada sem aviso).

### P2 — Erros de escrita não-duplicados ficam invisíveis fora de debug/warning logs

`_safe_execute` (`writer.py:602-612`) já diferencia mensagem de chave duplicada
(esperado, ignorado por design — `logger.debug`) de qualquer outra exceção
(`logger.warning`). O problema não é a diferenciação em si, é que **nenhum
chamador verifica o retorno de `_safe_execute`** para a maioria das escritas
(edges, sub-nós) — um erro real de tipo/schema é logado em `warning` (que a
maioria dos usuários nunca vê, já que builds normais rodam sem `--verbose`) e o
build termina reportado como sucesso, com nós/arestas faltando. `design-graph
validate` não detecta isso — só confere órfãos e tokens não usados, não que
toda entidade extraída foi de fato persistida.

## Solução proposta

| Task | Problema | Camada |
|---|---|---|
| T47 | P1 | `graph/writer.py` (`GraphWriteSession`) |
| T48 | P2 | `graph/writer.py` (`GraphWriter`) + `core/models.py` (`BuildStats`) + `pipeline/coordinator.py` + `cli/build.py` |

**T47** — `GraphWriteSession` adquire um lock exclusivo não-bloqueante
(`fcntl.flock(fd, LOCK_EX | LOCK_NB)`) sobre um arquivo sentinela
`.{name}.lock` antes de tocar o diretório temporário. Se o lock já está
tomado, levanta `BuildLockError` (nova exceção simples, `RuntimeError`) com
mensagem acionável (nome do banco, caminho do lock). O lock é liberado em
`__exit__` incondicionalmente (sucesso ou falha), depois de `_release_db()`.
Se qualquer etapa entre a aquisição do lock e o `return` de `__enter__`
falhar, o lock é liberado antes de propagar a exceção — do contrário o lock
vazaria porque `__exit__` nunca é chamado quando `__enter__` levanta.
`fcntl` é Unix-only; aceitável, o projeto já assume XDG/Unix em `paths.py`.

**T48** — `GraphWriter` passa a contar (não apenas logar) escritas que
falharam por motivo diferente de chave duplicada, num `list[str]` limitado
(primeiras 50 mensagens, para não crescer sem limite num cenário
catastrófico). `get_stats()` inclui `"write_errors": len(self._write_errors)`.
`BuildStats` (core/models.py) ganha o campo `write_errors: int = 0`.
`coordinator.py` propaga `raw_stats.get("write_errors", 0)` para `BuildStats`.
`cli/build.py` inclui `write_errors` na saída `--json` sempre, e no resumo
textual (`_print_build_summary`) só quando `> 0`, para não gerar ruído em
builds limpos (que são a maioria).

## Cobertura de testes exigida

- **P1/T47**: duas instâncias de `GraphWriteSession` para o mesmo `final_path`
  — a segunda, aberta enquanto a primeira ainda está dentro do `with`, levanta
  `BuildLockError`. Depois que a primeira sai do `with` (sucesso ou exceção),
  uma nova sessão adquire o lock normalmente. Regressão: uma sessão isolada
  (sem concorrência) continua funcionando exatamente como hoje.
- **P2/T48**: `_safe_execute` com uma statement inválida (não duplicata) é
  contado em `_write_errors`; `get_stats()["write_errors"]` reflete a
  contagem; uma chave duplicada continua não incrementando o contador.

Suíte completa (`pytest tests/unit/ -q`) sem regressão e guardrails
(`pytest tests/test_architecture_guardrails.py -q`) intactas; rebuild real
contra `iPede Manager v21.2.html` (DB descartável em `/tmp`) reportado no
`plan.md`.

## Segurança

Nenhuma nova fronteira de I/O externa — o lock é um arquivo local no mesmo
diretório do banco, já sob controle total do processo que roda o build.

## Fora de escopo

- Lock distribuído/cross-machine — fora do caso de uso (build local, único
  desenvolvedor por máquina).
- Superfície de retry/espera automática quando o lock está tomado — a decisão
  é falhar rápido e claro (`LOCK_NB`), não bloquear o processo chamador.
