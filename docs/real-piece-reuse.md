# Extração explícita de uma peça real (local)

O marco demonstrado é `SectorFormModal` do export existente **iPede Manager v21.2.html**. A fonte tem SHA256 `34b4469b68501e1f48a224af67194e98a0a7a9b1315429af3ae8a5125da9cb12`. O título HTML diz v21.1; o cabeçalho do kit diz v16. Esses rótulos distintos são preservados, não tratados como uma versão semanticamente comprovada.

## O que o produto oferece

Em uma **base nova**, módulos classificados como código próprio mantêm seu arquivo original em `Resource`/`Asset`. O CSS capturado também é um recurso explícito (`prototype stylesheet`). `get_resources` lista os nomes; `get_asset` grava os bytes no workspace e devolve caminhos com hash de conteúdo. Bibliotecas reconhecidas e runtime continuam descritivos, não são copiados pelo DG.

Isto usa o armazenamento de assets existente, sem tabela/campo novo. **Não existe fechamento automático de dependências**: selecionar um arquivo inteiro é uma operação explícita. A classificação de módulo pode ser inferida; nome não prova identidade de uma propriedade em runtime. CSS é a concatenação em ordem capturada, não promessa de cobrir folhas externas, URLs ou fontes ainda não resolvidas.

Bases antigas continuam legíveis, mas podem não ter os novos arquivos. O no-op de uma base antiga não a atualiza. Use destino novo ou rebuild explícito; não substitua sua única base.

## Entrada operacional desta demonstração

Checkout isolado: `/home/manoelmedeiros/Workspace/design-graph/.worktrees/t_14069c63`.
Evidências e scripts: `/home/manoelmedeiros/Workspace/design-graph/audit/t_14069c63`.
O virtualenv de benchmark fornece apenas o interpretador/dependências/console scripts; `PYTHONPATH` aponta para o checkout atual, **não** para o produto da release antiga.

```sh
cd /home/manoelmedeiros/Workspace/design-graph/.worktrees/t_14069c63
DG_BIN=/home/manoelmedeiros/Workspace/benchmark/v2/release-2.4.2/.venv/bin
export PYTHONPATH="$PWD/src"
export GRAPH_DIR=/home/manoelmedeiros/Workspace/design-graph/audit/t_14069c63/graphs
export XDG_CONFIG_HOME=/home/manoelmedeiros/Workspace/design-graph/audit/t_14069c63/config
# Interface MCP stdio existente, sem editar configuração/perfil UX:
"$DG_BIN/design-mcp"
```

Na sessão MCP, a sequência explícita verificada foi:

```json
{"tool":"search","arguments":{"query":"SectorFormModal"}}
{"tool":"get_full","arguments":{"aspect":"source","name":"SectorFormModal","doc":"candidate"}}
{"tool":"get_resources","arguments":{"doc":"candidate"}}
{"tool":"get_asset","arguments":{"name":"iPede Manager v16 — KIT COMPARTILHADO (DS canônico — design-system.md)","doc":"candidate"}}
{"tool":"get_asset","arguments":{"name":"prototype stylesheet","doc":"candidate"}}
```

O exemplo `recover_piece.py <novo-rótulo>` executa essa sequência pelo SDK stdio real. É uma receita da peça congelada, não um resolvedor genérico. Recusa envelopes de fonte inesperados; não raspa variantes ou interpreta Markdown arbitrário. Escolha um rótulo de saída novo: a receita não sobrescreve evidências.

```sh
python3 ../../audit/t_14069c63/run_bounded.py ux-recovery-once \
  "$DG_BIN/python" ../../audit/t_14069c63/recover_piece.py ux-recovery-once
```

Nenhum registro MCP do perfil UX, conta, restart global ou publicação foi feito. O fluxo acima é executável localmente; integração com a sessão UX em uso não foi demonstrada.

## Artefato navegável

```sh
python3 -m http.server 18764 --bind 127.0.0.1 \
  --directory /home/manoelmedeiros/Workspace/design-graph/audit/t_14069c63/served-r3
# Abrir http://127.0.0.1:18764/graph/
```

`graph/` contém a fonte do modal, kit conservador completo e CSS recuperados do DG. O adaptador local somente monta React, escolhe `K = window.V6K`, injeta `useState` e oferece callbacks criar/editar. Esse vínculo foi inspecionado manualmente na fonte original, não provado pelo grafo. `common/` é o ambiente controlado: React18.3.1/ReactDOM18.3.1/Babel7.29.0 retidos do próprio export e iguais nos três controles. Não são recuperação DG nem recomendação de runtime para produção. Não há backend, persistência de negócio, conta ou recurso remoto obrigatório.

## Evidência e limites

- `PROTOCOL.md`: peça/critérios/condições congelados antes da comparação; `READONLY-GATE.md`: falha e alternativas antes das alterações.
- Commits separados: retenção de módulo e retenção de CSS, cada um com RED comportamental e GREEN focal.
- `RESULTS.json`, recibos brutos e relatório em português: bytes/tokens efetivamente recuperados, custos separados, todas as falhas e desvios. Os três renderizadores são determinísticos; não houve geração de código por modelo.
- O DG permite recuperação seletiva fiel, sem dar o export inteiro ao consumidor. **Não venceu a busca/descompactação seletiva nem o recorte manual em custo/contexto neste caso.** Não confundir utilidade operacional delimitada com vantagem universal.
- O modal original só tem tema escuro. Foco inicial, Escape e overlay foram preservados. Ausência de trap no diálogo de setor e de retorno de foco ao abridor é um defeito herdado, não reparado escondidamente no adaptador.
- `get_full("Modal")` legado ainda agrega homônimos de unidades distintas com prosa de last-wins inadequada; não foi usado para escolher o valor de `K.Modal`. A seleção explícita do kit evita esse caminho, não o corrige.
- O build geral novo passou dentro do prazo existente. O caminho binding-owned completo do mesmo input atingiu timeout45s: não é um build aceito, nem prova de fechamento de dependências. Não houve aumento do deadline ou troca da baseline por release antiga.

A revisão independente no mesmo card e SHA final é uma etapa separada antes de considerar a tarefa concluída.
