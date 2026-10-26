# v5: B-only, geração sem navegador/servidor

Contrato `benchmark-ipede-v2`, protocolo `iPede-3pages-v5-B-only`. Esta entrada
não repete A: herda A/v3 por proveniência e mantém B/v3 inválido e v4 intactos.
Usa uma única sessão B, n=1, em scratch novo, separado e não aninhado ao baseline.
Não é um par contemporâneo nem uma estimativa causal de ganho: houve mudança de
protocolo/prompt e tempo de execução distinto. Não relabelar evidência histórica.

## Mudança delimitada

`run-b-v5` reutiliza o executor B-only v4, com seus defaults históricos preservados.
Fonte integral, input, recursos e selection são copiados/verificados contra o freeze
v3, sem refazer preparação ou escolher outras telas. Command/model, raciocínio,
900 segundos/90 ferramentas totais, sandbox workspace-write, regras herdadas,
OAuth existente e supervisão/refusal não mudam. Sem bypass, ignore-rules,
credenciais novas ou API alternativa. Nenhuma alteração no produto é necessária.

O prompt-base v5 mantém a tarefa herdada e explicita sua fronteira de geração.
O prompt histórico não ordenava servidor; v4 o abriu por iniciativa do executor.
Mantém o contrato de três páginas offline, seleção/estado congelados, shell e
interações relevantes, restrições de fonte/acesso, viewports e orçamento. Remove
tarefas de servir, abrir listener e autoavaliar em navegador. Ordena gerar
`output/page-1.html`, `output/page-2.html`, `output/page-3.html`, assets necessários
e finalizar. Proíbe browser, browser automation, servidor/listener inclusive
loopback, proxy/listener/API alternativos e contorno de refusal. Extração/cópia
de trechos relevantes não se torna reconstrução independente por causa desta
mudança; copiar/embutir/bootstrap do aplicativo inteiro continua proibido.

O prompt herdado permanece em `runs/B/prompt.txt`; o efetivamente enviado fica
em `runs/B/evidence/effective-prompt.txt`, com SHA256 em command, resultado e
`protocol-change.json`. `prompt.diff` registra a substituição inteira da base
herdada, não uma alegação de identidade textual. O TL deve revisar esse diff antes
de autorizar coleta; restrições adicionais de uma base histórica não são
transferidas automaticamente pela tarefa canônica. Nenhum desses arquivos com
conteúdo privado deve ir para git.

## Gate e execução: somente após revisão/autorização

Entradas disponíveis para execução posterior pelo TL, **não executadas na
implementação**:

```sh
PYTHONPATH="$PWD:$PWD/src" "$IPEDE_PY" -m scripts.ipede_threepages preflight-v5 --scratch "$V5" --python "$IPEDE_PY"
PYTHONPATH="$PWD:$PWD/src" "$IPEDE_PY" -m scripts.ipede_threepages run-b-v5 --baseline "$V3" --scratch "$V5" --python "$IPEDE_PY"
```

`IPEDE_PY` é o Python existente, preservando o symlink do virtualenv; `V3` é o
baseline somente leitura e `V5` um scratch privado novo. Revisar o preflight
antes de autorizar B; comandos acima não são autorização nem instrução de rerun.
Não usar `prepare`, `run` (duas condições), `evaluate` ou `report` históricos para
este scratch v5. Não há aceite/relatório v5 automático nesta correção mínima.

O gate separado `preflight-v5/gate.json` exige o mesmo executor/model/config,
initialize + initialized + tools/list, consulta útil nativa casada ao RPC real
e heading neutro. Além disso, exige `turn.completed` com usage **no próprio
evento nativo**: `input_tokens` e `output_tokens` numéricos, finitos e não negativos
(booleans, strings, null, NaN/inf não valem). Métricas agregadas ou sucesso
sintético não substituem esse evento. O gate v4 não é aceito como v5; identidade,
hashes e evidência são revalidados antes de qualquer subprocesso de B. Não mudar
instrumento/regras entre gate e B.

Indexação fria e readiness read-only são setup separado do tempo da sessão e não
contam como tratamento. B continua obrigada a consultas MCP nativas úteis para
**cada uma das três telas antes de qualquer output**, com matching RPC/nativo,
supervisão de output antecipado e parada em refusal/limite/timeout. O recorder
stdio mantém o MCP instalado real; não é proxy de rede nem substituto de API.
MCP ausente, tela não consultada, usage ausente, HTML ausente ou refusal invalidam
a tentativa. Não há fallback silencioso, segunda sessão, rerun ou afrouxamento.

## Evidência e limites

Resultados separados em `run-results-v5.private.json`; A é apenas referência de
proveniência. B só recebe input/selection congelados, nunca outputs de A/B,
evidência do avaliador ou conteúdo privado adicional. Logs brutos ficam privados.
`valid=true` significa conclusão do protocolo de geração, **não aceite**; v5
registra `generation_only=true` e `accepted=null`. Tempos observados de arquivos
não são tempos de aceite. Avaliação funcional/visual e auditoria de acesso são
fases separadas, posteriores e ainda necessárias. O avaliador usa file:// offline,
sem transferir o listener recusado para outra API/executor nem servir à sessão.

Usage é da sessão inteira; não oferece contexto por chamada, tamanho efetivo de
contexto, leitura de fonte por tela, splits de tokens por página ou custo. Não
inferir contexto desses totais. Cache de SO/modelo e não contemporaneidade
permanecem limitações; não publicar escore composto, generalização ou ganho causal.
Os testes usam fixtures sintéticas/mocks, não comprovam êxito de uma coleta real.
