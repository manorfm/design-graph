# Verificação da landing — t_71e2d5c2

Executado em 2026-10-26, somente neste worktree. Implementação estática; nenhuma
nova coleta ou execução de agente de benchmark. Commit local autorizado no card,
feito pelo agente pai após reexecução independente; sem push, main ou deploy.

## Requisito → implementação → evidência

| Requisito | Implementação | Evidência executada |
|---|---|---|
| Landing publicada preservada | Somente `site/`, `scripts/pages/` e `docs/pages/` materializados da revisão local `63042a7`; árvore de produto retida | Novo teste fixa hash do HTML original após remover somente seção/nav novos; CSS original é prefixo exato, JS/tema/mark inalterados; 5 contratos antigos passam com apenas seção, H2 e links adicionais |
| Fonte v5 autoritativa | Apenas os dois arquivos sanitizados copiados da entrega autorizada | SHA256 abaixo, testes estáticos e downloads reais byte a byte nos dois navegadores |
| Três dimensões | Seção `#benchmarks` antes de FAQ, link de navegação, copy em inglês, 32 valores com `data-source`/`data-value` | 7 testes focais estáticos; 12 casos de browser verificam atributos, valores apresentados e três tabelas |
| Fidelidade e limites | Original/A/B por página, seis MAEs B a 9 casas e seis zeros A, escopo congelado, falha mobile herdada e causalidade não identificada | Testes fixam rótulos, ausência de alegações de ganho, hashes e totais por lane; MAEs não quebram linha na matriz focal |
| Privacidade/export | Allowlist de oito arquivos públicos, somente report/data no subdiretório, links relativos com download | Export isolado, controles negativos de arquivo extra/symlink; HTTP 404 para diretórios, traversal codificado e arquivos do repositório |
| Regressão | Suíte Chromium antiga ampliada com largura 1280; estabilidade original intacta; matriz focal Chromium/Firefox | 23 checks da suíte completa, 13 controles de estabilidade, 12 casos focais; pytest normal e build neutro abaixo |

A normalização de preservação e os hashes dos assets estão em
`scripts/pages/test_benchmark.py`. Os contratos literais de comandos, exemplos,
links externos e segurança anteriores foram mantidos. O ajuste de layout do header
entre 640 e 1100 px acomoda o link adicional; CTAs e lógica de tema/clipboard
permanecem idênticos. Tabelas usam captions, cabeçalhos com scope e células que
acomodam texto; os números MAE permanecem inteiros numa linha.

## Arquivos públicos fixados

- `report.md`: `2c61f4b25a5eaaa1168984fd5aa9c49ca2c4a92036de8edd4ae47d8ecce3e08f`
- `data.json`: `b3bca3aa4107d50c518fc17cb6681a34a36832d24ff5994002da9b69ac701b27`

O relatório QA histórico v2 foi somente lido para resumir ressalvas, sem copiar o
arquivo nem publicar suas métricas numéricas. Nenhum protótipo privado, DOM,
screenshot de iPede, log bruto ou outro artefato foi copiado para `site/`.
Os PNGs desta verificação mostram apenas a landing pública.

A seção diferencia baseline do produto `ebdbeb24323d7143e0186622a7389b963e5ed350`
do código de medição `c68e1cbfd2c13ec5be68ae2a9314470a7c15652b`.
Versões ausentes da entrega v5 são declaradas não especificadas. As versões de
navegadores abaixo são da verificação desta landing, não da medição iPede.

## Comandos e resultados

Ambiente reutilizado somente para executar ferramentas:
`/home/manoelmedeiros/.hermes/cache/scratch/ipede-benchmark-t_48a71d3b/venv/bin/python`.
Não houve instalação ou alteração desse ambiente. Nos comandos abaixo, `PY` aponta
para esse executável e `SCRATCH` para
`/home/manoelmedeiros/.hermes/cache/scratch/ipede-benchmark-t_48a71d3b/landing-t_71e2d5c2`.
`TMPDIR=$SCRATCH` foi definido para pytest, build e browser runners.

| Comando | Resultado |
|---|---|
| `python scripts/pages/test_static.py` | 5 testes, OK |
| `python scripts/pages/test_benchmark.py` | 7 testes, OK |
| `$PY scripts/pages/test_browser.py` | 23 checks PASS, Chromium 156.0.8078.4 |
| `$PY scripts/pages/test_browser_stability.py` | 13 controles PASS, incluindo controles negativos de contraste e timeout |
| `$PY scripts/pages/test_benchmark_browser.py` | 12 casos PASS, Chromium 156.0.8078.4 e Firefox 157.0; nenhum browser ausente |
| `$PY -m pytest -q` | 2642 passed, 7 skipped, 1 warning em 122.49 s |
| `PYTHONPATH="$PWD/src" make build PROTO=tests/fixtures/simple.html DB_DIR=$SCRATCH/build GRAPH_DB=$SCRATCH/build/neutral.db DESIGN_GRAPH=/home/manoelmedeiros/.hermes/cache/scratch/ipede-benchmark-t_48a71d3b/venv/bin/design-graph` | PASS: 1 tela, 2 componentes, 2 tokens e 2 seções |
| `python scripts/pages/export.py .venv/benchmark-public-export` | PASS, export local isolado, sem publicação |
| `python -m compileall -q scripts/pages` | PASS |
| `git diff --check` e verificação de whitespace dos arquivos novos | PASS |

Pytest usa o `testpaths=tests` normal. O aviso é a depreciação preexistente de fixture
class-scoped em `tests/unit/scripts/test_context_benchmark.py`; os números acima são
resultados deste worktree, não os resultados históricos citados no report v5.
O build usou apenas a fixture neutra do repositório e banco scratch do dono.

A matriz focal cobre temas dark/light com JavaScript, mais dark sem JavaScript,
em 1280×900 e 390×844 por navegador. Cada caso verifica 32 valores e dois downloads
contra os hashes fixos; sem erros de página/console/requisição ou pedidos externos.
Contraste mínimo de texto observado: 6.0150:1, com os mesmos limites AA 4.5/3 e
3:1 para bordas. O runner completo também mantém 1440/768/320, clipboard real,
estados de erro, storage, FAQ, foco/teclado, hover, reduced-motion e reflow.

O helper original Chromium de estabilidade usa requestAnimationFrame. No modo sem
JavaScript, o runner focal observa animações pelo driver com deadline de 5 s e
avalia contraste uma vez após estabilizar; não repete nem tolera falhas de contraste.
O tema claro da matriz focal é carregado pela preferência persistida, antes do
render. A suíte Chromium completa mantém os testes do toggle real.

São checks automáticos, não auditoria assistiva manual nem certificação de WCAG.
Eles verificam a apresentação da landing, sem revalidar causalidade, reconstruir
protótipos ou encerrar o QA independente pendente do benchmark.

## Evidência durável

Diretório autorizado, fora de `site/` e do scratch:
`/home/manoelmedeiros/.hermes/profiles/dev-codex/artifacts/t_71e2d5c2/`.

Contém logs dos comandos, `verification.json`, inventário SHA256,
`pages-evidence/browser-report.json`, `contrast-evidence/stability/stability-report.json`
e `benchmark-browser-evidence/benchmark-browser-report.json`, mais capturas da
landing. Cópias locais de trabalho ficam em `.venv/`, ignorado pelo git.
Cada runner fecha seus próprios contextos/browser e servidor em `finally`.
Nenhum recurso ou servidor alheio foi encerrado.

## Reexecução independente do agente pai

Antes do commit local, os 5 contratos estáticos originais e 7 focais passaram
novamente. A matriz focal passou em 12/12 casos Chromium/Firefox, sem navegadores
ausentes, erros ou pedidos externos; o runner Chromium completo passou os 23
checks e a estabilidade passou os 13 controles. Pytest foi reexecutado:
2642 passed, 7 skipped, 1 warning em 121.13 s. Capturas desktop claro e mobile
escuro foram também inspecionadas visualmente, incluindo recorte das tabelas.
As quebras de palavras nas células mobile são esperadas; valores MAE permanecem
íntegros e não houve corte nem sobreposição observados.

Provas da reexecução têm prefixo `parent-` no mesmo diretório durável. O handoff
inclui bundle Git local e ZIP da evidência, ambos fora de `site/`, com SHA exato
do candidato no registro da tarefa. Após persistir a evidência, só o banco neutro
e diretórios pytest deste subdiretório proprietário do scratch são descartados.
O ambiente compartilhado e as fontes recebidas permanecem intactos.

O grafo já contém o filho QA `t_3c887fcc`: concluir esta fase libera esse gate,
sem duplicar revisão no mesmo card. QA/TL downstream continuam obrigatórios;
nenhuma aprovação editorial final ou publicação é inferida destes testes.
