# iPede — B/v5 concluída; comparação de artefatos com A/v3 preservado

Contrato: benchmark-ipede-v2 · iPede-3pages-v5-B-only · 2026-10-26 · commit c68e1cbfd2c13ec5be68ae2a9314470a7c15652b.

## Veredito

PASS técnico: uma nova B finalizou normalmente, emitiu usage real, consultou as três telas por MCP nativo antes dos outputs e foi avaliada offline. O aceite técnico não exige vitória. A comparação visual é parcial, a equivalência funcional integral não está certificada e o ganho causal NÃO É IDENTIFICADO. QA downstream pendente.

## Autorização e comparabilidade

A autorização vigente de Manoel (“Vamos de B então”) substituiu o pedido histórico de repetir o par: preservamos A/v3, B/v3 inválido, B/v4 interrompido e todas as provas. Houve apenas uma nova B/v5. Fonte integral, input, selection/defaults, modelo gpt-6.1-sol, raciocínio medium e limites de 900 s/90 ferramentas foram mantidos. Pré-revisão e freeze ocorreram antes do preflight e da coleta.

O prompt v5 explicita somente geração de output/page-1.html, page-2.html, page-3.html e assets e finalizar, sem navegador, listener ou autoavaliação em browser. O prompt v3 não ordenava servidor: v4 tomou essa iniciativa. Diff/hash do prompt efetivo foram arquivados. MCP continua obrigatório nas três telas; não foi criada nova restrição assimétrica de extração. Não houve alteração de produto, sandbox, política global, credenciais ou rede. A/v3 não usava sandbox equivalente; B herdou workspace-write/regras. Não se trata de A/B contemporâneo nem comparação causal.

## Evidência e tempos

| Medida | A/v3 preservado | B/v5 nova |
|---|---:|---:|
| Sessão, segundos | 341.454470 | 407.376318 |
| Input tokens agregados | 1817773 | 2742036 |
| Output tokens agregados | 12461 | 12840 |
| Tempo de aceite por página | indisponível | indisponível |

B: 2631040 cached input tokens; reasoning_output_tokens=4292 como campo separado do provedor (não somar de novo a output sem semântica comprovada). 61 ferramentas de 90; exit 0, turn.completed, sem stop/refusal. Setup integral frio=5.374725 s; readiness read-only=0.493726 s; supervisão=0.000527 s; pós-processamento=0.137238 s, todos separados. A medida principal é geração e não tempo de aceite. Não há percentual de ganho/score ou custo calculado.

Preflight neutro pelo mesmo executor: initialize + initialized + tools/list, catálogo de 15 ferramentas e consulta nativa útil cruzada com RPC; turn.completed com usage real. Usage/tempo do preflight não pertencem a B. Índice integral e readiness das três telas comprovados antes da sessão medida.

B teve 31 chamadas MCP cruzadas: 20 consultas substantivas alvo-corretas, 1 resposta com entidade divergente, 3 descobertas/listagens, 1 configuração e 6 diagnósticos. Não chamar as 31 de consultas úteis. As três telas já estavam cobertas antes do primeiro output; diagnósticos de nome não encontrado não foram contados como cobertura. Sem acesso indevido/servidor/browser/contorno identificados nos rastros, inclusive comandos, writes, build e verificação Node/VM. Isso não prova isolamento de syscalls.

Não há contexto efetivo por chamada, compactions, resets, truncamentos ou limite backend observado. Input agregado de milhões soma a sessão, não é janela de contexto nem prova de estouro/ausência de estouro. Não inferir splits por tela.

## Avaliação independente

Após encerrar B, avaliação por file:// offline, sem servidor/listener/proxy, nos três lanes (original/A preservado/B nova), 1280×900 e 390×844: 18 contextos frescos; data fixa, locale pt-BR, timezone America/Fortaleza, rede externa bloqueada. 86/86 passos congelados por lane (11/15/17 por tela em cada viewport), nenhum erro de navegador, captura ou requisição externa. Os 12 PNGs default original/A são idênticos aos históricos. Browser fechado.

| Página | A | B/v5 |
|---|---|---|
| Grupos de Componentes | Default idêntico ao original; plano funcional PASS | Omissões em vários ícones da sidebar; conteúdo principal e shell mantidos, com pequenos desvios de espaçamento. Plano congelado PASS |
| Restaurantes | Default idêntico ao original; plano funcional PASS | Omissões em vários ícones da sidebar e posicionamentos ligeiramente diferentes; default Premium mantido. Downloads/CSV adicionados fora do plano congelado. Plano congelado PASS |
| Estoque | Default idêntico ao original; plano funcional PASS | Omissões em vários ícones da sidebar, abas e header; KPIs com placeholders cinza vazios em vez dos ícones coloridos. Pequenos desvios de espaçamento. Escopo rede/visão geral mantidos. Plano congelado PASS |

Em 390×844 a sidebar larga ocupa a maior parte da largura e o conteúdo/tabelas fica cortado nos três lanes. É deficiência herdada do original, não aprovação de usabilidade mobile. A mantém fidelidade visual default nos screenshots; B não é pixel-perfect. Em Estoque, os KPIs preservam os contêineres cinza, mas perdem seus ícones coloridos; também faltam ícones em abas e header.

Fora do plano, B acrescenta downloads XLSX/CSV em botões originalmente inertes; “Imprimir contagem” passa a baixar CSV. Dados do export de restaurantes são seed estático, não garantia de estado editado/filtrado. Esse comportamento é invenção/divergência, não ganho funcional. Fluxos não cobertos, downloads e fidelidade global permanecem não certificados. A avaliação não usou somente screenshots.

A reutiliza faixas da fonte; B seleciona AST, transpila componentes/dependências e usa wrapper próprio. Nenhum bootstrap da aplicação integral foi identificado. Isso é reutilização/extração relevante permitida nesta repetição, NÃO reconstrução independente. Há dependências e dados compartilhados além das três rotas; inferência de eficiência de contexto é limitada.

| B: diagnóstico RGB MAE normalizado | 1280×900 | 390×844 |
|---|---:|---:|
| Grupos de Componentes | 0.002589892 | 0.009569123 |
| Restaurantes | 0.003561452 | 0.009765555 |
| Estoque | 0.010074183 | 0.011224980 |

MAE é diagnóstico de diferença de pixels, não percentual de similaridade/qualidade, escore composto ou aceite. Screenshots, montagens, DOM, plano funcional e logs estão somente na custódia privada.

## Histórico e limites

B/v3 permanece inválido (zero MCP); B/v4 permanece interrompido por guard após MCP, sem usage final. Nenhuma métrica deles compõe B/v5. A/v3 é preservado sem nova sessão. Todos os membros de baseline-v3 e experiment-v4 foram rechecados byte a byte contra os arquivos duráveis, sem diferenças.

- n=1; A/v3 preservado e nova B/v5 não contemporâneos; mudança de prompt e fronteira geração/avaliação.
- A/v3 sem sandbox/políticas equivalentes; B usa workspace-write e regras herdadas; comparação causal inválida.
- Preparação v3 contém localização de fontes; A copia faixas, B seleciona/transpila AST. Não são reconstruções independentes.
- Usage agregado por sessão não é janela/contexto por chamada. Indisponível não significa zero ou ausência de estouro.
- Plano funcional congelado tem 86 passos por lane; não certifica equivalência integral e não cobre downloads/CSV acrescentados em B.
- Mobile reproduz deficiência original: sidebar larga e conteúdo/tabelas cortados; fidelidade não é usabilidade.
- RGB MAE é diagnóstico normalizado de pixels, não percentual de similaridade, escore composto ou aceite visual.
- Tempos de arquivos são observações reativas de 50 ms; geração não equivale a tempo de aceite.
- Cache de SO/modelo não controlado; custo monetário e splits por página indisponíveis.
- Auditoria de eventos/RPC/código não prova isolamento de syscalls. QA downstream ainda pendente.

## Verificação e handoff

Suíte: 2728 passed, 7 skipped, 1 warning de depreciação pytest preexistente. Testes focais: 60 passed. make build com fixture neutra: PASS (1 tela, 2 componentes, 2 tokens, 2 seções). git diff --check: PASS. Process groups de preflight/B encerrados; contextos browser fechados. Nenhum push, main, produção ou publicação externa. Commit local no worktree do card; não há branch de integração documentado no repositório.

report.md e data.json são as únicas peças sanitizadas para o QA t_3c887fcc e a landing t_71e2d5c2 existentes. Custódia privada v5 tem hashes do instrumento, evidência bruta, avaliações, fonte, outputs e plano reprodutível; histórico v4 fica separado. Não publicar logs, fonte privada, screenshots, caminhos locais, IDs de sessão ou arquivos de custódia. QA deve auditar sem lançar novos agentes medidos; não há nova repetição autorizada.
