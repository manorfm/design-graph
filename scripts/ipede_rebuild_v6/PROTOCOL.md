# ipede-rebuild-v6 — preparação independente

Escopo: preparar e congelar; nenhuma reconstrução medida nesta implementação.
O histórico fornece somente código genérico de execução e registro. Não fornece
baseline, outputs, escolhas de páginas, resultados ou autorização.

## Desenho congelado

Três pares, uma página e uma sessão nova por lane. Ordem: página 1 A/B,
página 2 B/A, página 3 A/B. Modelo `gpt-6.1-sol`, esforço `medium`, 900 segundos,
120 operações por sessão, sandbox `workspace-write`, políticas herdadas.
Uma operação é um item distinto de ferramenta nativa; started/completed do mesmo
ID contam uma vez. Até 120 IDs distintos são permitidos, inclusive a conclusão da 120ª. Ao observar
a 121ª o supervisor invalida a sessão e encerra seu grupo de processos. Comandos shell compostos não equivalem a múltiplas operações nativas;
subcomandos são diagnósticos e nunca somam ao total de operações. Erros incluem
exit_code diferente de zero e são deduplicados pelo mesmo ID; ID ausente invalida.
Eventos reais nunca são descartados para aparentar cumprimento do orçamento. Há resolução de observação de
50 ms: operações já em voo podem terminar; uma ultrapassagem invalida a sessão.

A usa arquivos e busca, sem MCP. B recebe os mesmos bytes e ferramentas mais
MCP stdio real e precisa consultar informação relevante antes de escrever a
implementação. Descoberta, eco, consulta irrelevante ou posterior à escrita
invalidam B. As declarações de tratamento são a única diferença nos prompts.
Os prompts comuns não incluem offsets, localização de componentes, seletores,
roteiros privados ou respostas. `target.json` contém apenas título e estado.
Acesso visual compartilhado congelado: **nenhum**; oracle real exclusivamente
privado. Ambos podem consultar os mesmos bytes e decodificar mecanicamente todo
o bundle. Ninguém pode copiar/transpilar CSS, componentes, app ou framework.
Somente imagens estáticas originais podem servir de assets.

Alvos: listagem de itens; cadastro de promoções aberto na identificação; Estoque
na visão geral da rede. A decisão semântica e a navegação observada ficam na
custódia privada. Não se substituem por outras páginas. Renderização preparatória
é `file://`, offline, sem listener, em 1280×900 e 390×844. Interações locais
observadas são o limite da implementação; controles inertes não ganham backend.
Geração permanece sem browser/listener. Avaliação funcional e visual é fase
separada, ainda não executada. Aceitação exige revisão privada do oracle e dos
traces; o scanner automatizado não prova independência semântica.

## CLI e dependências

Python >=3.10; dependências do projeto mais `.[dev]`, `playwright` e Chromium.
Crie venv local; nunca altere ambiente ou configuração global. Execute da raiz:

```text
python -m scripts.ipede_rebuild_v6 prepare --root SCRATCH --source ORIGINAL --plans PLANO_PRIVADO --targets ALVOS_PRIVADOS [--graph DB_INTEGRAL]
python -m scripts.ipede_rebuild_v6 preflight --root SCRATCH
python -m scripts.ipede_rebuild_v6 freeze --root SCRATCH
python -m scripts.ipede_rebuild_v6 validate --root SCRATCH
python -m scripts.ipede_rebuild_v6 materialize --root SCRATCH
python -m scripts.ipede_rebuild_v6 manifest --root CUSTODIA
```

`collect` existe exclusivamente para o card downstream e exige aprovação TL
externa, não vazia, com `approved: true`, `reviewer_role: TL`, identidade,
data e `freeze_sha256` exato. O freeze sempre cria aprovação pendente `{}`.
Não preencher esse arquivo nesta implementação. Sem oracle real, readiness,
preflight íntegro, identidade idêntica e aprovação, nenhuma coleta pode começar.
Alteração de instrumento/ambiente/preparação invalida o freeze e o preflight.
Não há retry automático. Refusal encerra a ação e preserva os registros; nenhuma
API, túnel, sandbox relaxado ou executor alternativo pode reparar uma recusa.
O caminho real de TMPDIR é verificado antes de executar; não se usa alias para
encurtá-lo. Preflight usa a mesma fábrica de comandos, executor, modelo, esforço,
budget e configuração de B, com fixture neutra em lugar da fonte privada.

## Evidências e fronteiras

No Git: instrumento genérico, testes neutros, protocolo, report/data e schemas
públicos saneados. Fora do Git/site: fonte, planos, DOM, capturas, RPC, eventos,
comandos, checkpoints e hashes de custódia. Scratch e custódia são exclusivos do
card; caminhos concretos somente no recibo privado e na entrega ao responsável.
Nunca ler `.env`, `auth.json` ou conteúdo de credenciais. Configurações herdadas
são identificadas por hash sem publicar seu conteúdo. Sessões não recebem oracle,
preflight, evidências, offsets, scripts preparados ou outputs históricos.
O sandbox herdado limita escrita; não constitui isolamento de leitura. Traces e
revisão de acesso são gates obrigatórios e essa limitação deve acompanhar dados.

Retenção: JSONL bruto e observado, bytes bidirecionais de RPC, stderr, comandos,
contagem por tipo, erros, estado de limpeza, checkpoints e proveniência. Usage
vem do final real por sessão; cache é subconjunto da entrada. Valores ausentes,
contexto efetivo, tarifa/custo não verificável e resultados não coletados são
`null`. Não ratear usage de sessão nem inferir contexto a partir de input total.
Setup/index, preflight, geração, supervisão e avaliação têm tempos separados.
Aprovação não valida outputs automaticamente; scanners e revisão privada bloqueiam
aceitação e publicação. Não se publicam fonte, DOM, capturas nem transcrições.

O manifesto privado exclui somente a si próprio, recalcula todos os hashes
SHA-256 e verifica o conjunto de evidências duráveis. Recursos próprios são
encerrados; evidência histórica e processos alheios ficam intactos.

## Proveniência genérica

Adaptados de `c68e1cbfd2c13ec5be68ae2a9314470a7c15652b`:
runner (somente executor), common, native_audit, stdio_recorder e preflight.
Nenhum código de produto, landing, avaliação ou seleção histórica foi importado.
Configuração nativa conferida em OpenAI Docs:
https://learn.chatgpt.com/docs/non-interactive-mode e
https://learn.chatgpt.com/docs/extend/mcp?surface=cli.

## Rubrica e efetividade (reforço de escopo antes do freeze final)

`rubric.public.json` publica somente denominadores e thresholds. Para cada
alvo/viewport, `preparation/rubric.private.json` fixa IDs e referências SHA-256
para TODOS os estados já observados no oracle principal, variantes e ações
locais. Não captura nem reconstrói novos outputs. Cada estado conta cinco asserts
visuais (geometria, tipografia, paleta, controles, conteúdo), um assert funcional
(texto normalizado e controles ordenados, valores/visibilidade/disabled) e dois
de usabilidade absoluta (alcance das ações e legibilidade/ausência de clipping).
Entradas, ações e expected states concretos são privados. Normalizar texto =
colapsar whitespace para um espaço e trim em cada string; controles mantêm ordem,
tags, valores, flags e número exatos. Human reviewer verifica também rede/download
para ações inertes. Os asserts não inventam comportamento backend.

Fidelidade visual >=90%, funcional 100%, usabilidade 100%, separadamente nos dois
viewports. Um check é booleano, sem crédito parcial; ausente=null, nunca aprovado
nem zero. Denominador nunca diminui. Uma falha crítica reprova equivalência:
alvo errado, output vazio, estado obrigatório ausente, backend inventado, cópia,
geração proibida, acesso não revisado, ação primária inacessível ou orçamento
excedido. Margem de equivalência = 0 por dimensão/viewport: B não pode piorar
nenhum score de A. A e B precisam atingir thresholds, sem falhas críticas, dentro
do mesmo orçamento. MCP mede somente aderência ao tratamento.

Clipping mobile herdado no alvo 3 é negativo do original: reproduzi-lo pode
aprovar fidelidade e reprovar usabilidade; nunca é mérito do MCP. Original e
resultados não são confundidos. Branches combinados não são exaustivos.

Para cada recurso, delta=B-A; delta_pct=100*(B-A)/A. A=0/null ou B=null =>
percentual null; qualquer métrica ausente => delta absoluto null. Entrada,
cache (subconjunto, sem somar), saída, operações, tempo de geração, supervisão,
avaliação e dinheiro ficam separados. Setup é tempo real de indexação integral,
sem ratear por página. Totais somam seis sessões somente se todas as parcelas
existirem; total geração+setup é mostrado à parte. Preflight nunca entra no total
medido. Totais por lane (três sessões cada), deltas agregados e B+indexação uma
única vez versus A são expostos separadamente; não são réplicas adicionais.
Dinheiro permanece null: não há tarifa verificável implementada.

Classificação conservadora (n=1 por alvo; estudo de caso): qualidade equivalente
ou superior e nenhum recurso maior, com ao menos um menor => “economizou mantendo
qualidade”; qualidade superior e recursos iguais ou maiores, com algum maior =>
“melhorou qualidade com custo adicional”; B dominado por A (qualidade igual/pior,
recursos iguais/maiores) => “não trouxe ganho”; troca não dominada, dado ausente,
resultado inválido/incompleto/reprovado => “inconclusivo”. Recursos de decisão:
input, output, segundos de geração e operações. Cache é reportado e precisa
existir, mas maior cache não é tratado como maior custo. Dinheiro/contexto sem
medição não impedem comparação de recursos físicos, nem autorizam conclusão
monetária. Qualidade superior com recursos exatamente iguais fica inconclusiva
por lacuna explícita desta taxonomia. Preservar números e negativos em todos casos.

`materialize` lê seis `sessions/{page}-{lane}/evidence/metrics.json` reais;
`evaluation.private.json` é avaliação DOWNSTREAM humana vinculada por hash ao
freeze, rubrica, HTML, eventos e métricas. Os schemas privados por alvo estão
na preparação. Revisões humanas de traces, acesso e independência são gates
obrigatórios antes de accepted=true. Scanner limpo não substitui esses gates.
O comando não avalia nem preenche checks: apenas valida, agrega e materializa
`results/data.json` e `results/report.md` saneados em diretório novo. Na ausência
de coleta, resultados continuam null. Aprovação TL nunca é inferida/escrita pelo
helper. Schema público valida métricas, scores, denominadores e comparações;
`results.validate_data` verifica também aritmética e decisões.

O gate de geração rejeita invocações evidentes de browser/listener/network,
framework/transpilação, web/agentes e acessos oracle/parent/sibling; arquivos de
retorno de consultas não são tratados como invocações. Indireção, código
ofuscado, imports com alias e leitura absoluta construída podem escapar ao scan:
não existe sandbox de isolamento de leitura. Revisão humana dos traces e da
origem do código é mandatória, podendo rejeitar qualquer output. Sem instalação
de plugins ou alteração de políticas. O limite nativo é observado a cada 50 ms:
uma 121ª invocação já pode começar antes da interrupção; isso INVALIDA a sessão,
jamais trunca o contador. Não há enforcement preventivo por ferramenta no CLI
herdado; esta é uma limitação concreta, sem bypass para contorná-la.

Freeze bb41ab e preflights anteriores são preparação supersedida pelo reforço
de escopo, arquivados com hashes; nunca baseline nem coleta. Novo instrumento
invalida a identity anterior. O novo preflight neutro exige freeze íntegro ANTES
do primeiro Popen e registra seu SHA no gate. Refusal encerra sem repetição.
