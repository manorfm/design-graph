# Instrumento pós-coleta

Contrato público `benchmark-ipede-v2`, rodada `iPede-3pages-v3`. Instrumento offline;
nenhuma execução de agentes, coleta, resgate ou revisão automática de conteúdo.

Após existir `ROOT/manual-findings.private.json`, executar:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m scripts.ipede_threepages.posthoc --scratch ROOT
```

Lê `run-results.private.json`, `evaluation-results.private.json`, os streams
`runs/A/evidence/events.jsonl` e `runs/B/evidence/events.jsonl`; lê também
`manual-findings.private.json` e `model-context-observation.private.json` se presentes.
Sem revisão manual, os vereditos ficam null. Esta implementação não deve ser
executada sobre a rodada real antes de existir o arquivo de revisão manual.
Cria `ROOT/posthoc/` usando `fresh`: destino existente causa erro, sem sobrescrever.
`data.json` contém dados sanitizados; `report.md` contém o resumo PT-BR.
Não lê source, preparation, freeze, screenshots ou credenciais.

O schema manual é:

```json
{"pages":[{"lane":"A","page":1,"visual_verdict":"PASS","state_verdict":"PASS","content_verdict":"FAIL","functional_scope_verdict":"PASS","unsupported_content":"not_observed_in_reviewed_scope","omission_codes":["CONTENT"],"private_notes":"privado"}],"hypothesis_verdict":"INCONCLUSIVO","private_report":"privado"}
```

Lanes permitidas: A/B; páginas: IDs 1/2/3; vereditos: PASS/FAIL.
`unsupported_content`: `observed` ou `not_observed_in_reviewed_scope`; este último
se restringe ao escopo revisado. Campos ausentes/inválidos ficam null.
Códigos genéricos permitidos: LAYOUT, STYLE, CONTENT, STATE, INTERACTION,
NAVIGATION, ASSET, RESPONSIVE, ACCESSIBILITY, OTHER. Outros códigos viram OTHER.
Lista vazia significa nenhum código registrado, sem inferir completude.
Revisões duplicadas de uma lane/página são rejeitadas. Hipótese permanece
INCONCLUSIVO independentemente de texto privado ou veredito informado.

Só categorias fixas e números tipados saem. Nunca são exportados notas, relatório
privado, nomes de páginas, conteúdo, caminhos do cliente, comandos ou outputs.
IDs de comandos `item_N` são preservados; IDs fora desse formato recebem
`command_N` na ordem dos comandos concluídos, evitando caminhos em identificadores.
Exit codes negativos são preservados. Falhas permanecem mesmo se uma duplicata
posterior tiver sucesso. Itens sem ID não são contados como ferramentas únicas.

Comandos são contados apenas em `item.completed`, por ID único. MCP tem contagens
únicas de started/completed e da união de IDs; as duas fases não são duas chamadas.
Thread starts, turn starts e eventos com usage são contagens de eventos.
`raw_aggregate_usage` preserva snapshots numéricos de `turn.completed` sem somá-los;
`last_session_aggregate_usage` é o último snapshot, não uma soma de requisições.
Campos de usage: input_tokens, cached_input_tokens, output_tokens,
reasoning_output_tokens; detalhes cached_tokens/reasoning_tokens nos objetos
input_tokens_details/output_tokens_details. Cache é subconjunto de input;
reasoning é subconjunto de output. Nenhum rateio por página, preço ou estimativa
monetária. Os agregados do runner não substituem o stream raw JSONL.

Sem telemetria tipada, maior contexto real, tokens por chamada, limite do backend,
compactions, resets e truncations ficam null. O schema explícito opcional
`type=context.telemetry` aceita apenas números não negativos nas chaves
`largest_observed_context_tokens`, `tokens_per_call`, `backend_context_limit`,
`compaction_count`, `reset_count`, `truncation_count`; não é inferido de usage.
Erros de contexto contam apenas `event.type=context_length_exceeded`,
`event.type=error.context_length_exceeded` ou `event.error.code=context_length_exceeded`,
no máximo uma vez por evento. Texto de source, output e mensagens não é pesquisado.
Zero significa nenhum evento estruturado nesse stream, sem provar ausência de estouro.

Da observação de configuração saem apenas advertised_context_window_tokens,
advertised_effective_context_window_percent, calculated_effective_context_window_tokens
e advertised_tool_output_truncation_policy.limit (renomeado para
advertised_tool_output_truncation_limit). Os anúncios 500000/95% não comprovam
contexto usado, limite aplicado ou truncation ocorrida.

`accepted_seconds` é sempre null: checkpoint HTML não é tempo até aceitação,
as dependências finais podem ter mudado e a revisão veio depois. Diferença pixel
é diagnóstica, sem conversão em percentual de precisão. Output observado não
prova alucinação. n=1 por lane e B sem consultar MCP impedem conclusão causal;
não sustentam afirmar que o produto perdeu. Mesmos inputs integrais, porém ambos
receberam offsets sob o contrato antigo antes da nota tardia, violando a nova
exigência de informação de localização. Uma tentativa A/B cada, sem rerun ou
resgate; retries internos do provider indisponíveis.
