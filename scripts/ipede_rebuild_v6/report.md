# ipede-rebuild-v6

Status: **NÃO COLETADO; aprovação TL pendente**.

Protocolo e schemas congeláveis; resultados de geração e avaliação são `null`.
Modelo gpt-6.1-sol, esforço medium, sessão nova por página/lane, 900 s e 120
operações. Ordem: 1-A, 1-B, 2-B, 2-A, 3-A, 3-B. Fonte, identidade e freeze são
identificados por SHA-256 em data.json; evidências detalhadas são privadas.

Alvos: listagem de itens, cadastro de promoções, Estoque. O oracle privado real
observa o original offline nos dois viewports; não é fornecido aos executores.
O preflight neutro é preparação e seu usage nunca é atribuído a uma página.
Tempos de setup, preflight, geração e avaliação permanecem separados.

Nenhum valor ausente é substituído por zero. Contexto efetivo e dinheiro sem
medição/tarifa verificável permanecem `null`. Cache é subconjunto de entrada.
Não há baseline herdado nem resultado medido nesta entrega.

Validade exige freeze íntegro, revisão TL vinculada ao hash exato, preflight
nativo com catálogo/RPC/turn.completed/usage, consulta B relevante antes da
primeira escrita, paridade de inputs e auditorias de acesso/cópia. Aceitação
funcional/visual exige avaliação privada futura. Scanner de strings não prova
independência; o sandbox herdado restringe escrita e requer auditoria de leitura.

Formato público: este report e data.json; campos obrigatórios definidos em
data.schema.json. Estado de validação, métricas e proveniência de cada sessão
são desconhecidos até coleta autorizada. Traces, caminhos pessoais, capturas,
fonte e oracle não são publicados.

Efetividade usa qualidade visual, funcional e usabilidade por viewport com
denominadores fixos em rubric.public.json, sem scores antes de avaliação real.
Deltas: B−A e 100×(B−A)/A; A zero/null => percentual null. Resultado pior ou
incompleto não conta como economia equivalente. MCP é apenas aderência.
Conclusões: economizou mantendo qualidade / melhorou qualidade com custo adicional /
não trouxe ganho / inconclusivo. n=1 por alvo, estudo de caso.

O helper `materialize` gera report/data de seis sessões e avaliação humana futuras,
com setup sem rateio e total com setup separado. Nenhum output foi reconstruído.
Limitações: scan não detecta toda indireção; leitura não é isolada; interrupção
é observacional (121ª operação invalida); original mobile com clipping continua
negativo de usabilidade. Rubrica não cobre todas as combinações de estados.
