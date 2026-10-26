"""Offline post-collection export. Only fixed categories and typed numbers leave scratch."""
from __future__ import annotations
import argparse
import json
import math
import re
from .common import CONTRACT, ROUND, fresh, root_path, write_json

LANES = ('A', 'B')
VERDICTS = {'PASS', 'FAIL'}
REVIEW_FIELDS = ('visual_verdict', 'state_verdict', 'content_verdict', 'functional_scope_verdict')
OMISSION_CODES = {'LAYOUT', 'STYLE', 'CONTENT', 'STATE', 'INTERACTION', 'NAVIGATION',
                  'ASSET', 'RESPONSIVE', 'ACCESSIBILITY', 'OTHER'}
USAGE_FIELDS = ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens')
CONTEXT_FIELDS = ('largest_observed_context_tokens', 'tokens_per_call', 'backend_context_limit',
                  'compaction_count', 'reset_count', 'truncation_count')
OBSERVATION_FIELDS = ('advertised_context_window_tokens', 'advertised_effective_context_window_percent',
                      'calculated_effective_context_window_tokens')
LIMITATIONS = [
    'n=1 em cada condição; B sem MCP consultado não permite atribuir efeito causal ao MCP nem concluir que o produto perdeu.',
    'Ambos receberam os mesmos inputs integrais e offsets preparados pelo contrato antigo antes da nota tardia; a informação de localização viola a nova exigência.',
    'Uma tentativa A e uma B; sem rerun ou resgate. Retries internos do provider indisponíveis.',
    'accepted_seconds é sempre null: checkpoint HTML não mede tempo até página aceita; dependências finais podem ter mudado e a revisão ocorreu depois.',
    'Uso em turn.completed é agregado da sessão, não uma requisição ao modelo; sem rateio por página ou soma de snapshots.',
    'Cache é subconjunto do input; reasoning é subconjunto do output. Não somar novamente. Dinheiro indisponível.',
    'Zero erros estruturados significa nenhum evento desse tipo no stream; não prova ausência de estouro de contexto.',
    'Configuração de cache anunciada não demonstra limite aplicado pelo backend nem maior contexto real.',
    'Métrica pixel é diagnóstico de diferença, não percentual de precisão. Output observado não prova alucinação.',
]


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def integer(value):
    return value if type(value) is int else None


def usage(value):
    if not isinstance(value, dict):
        return {}
    safe = {key: number(value[key]) for key in USAGE_FIELDS if key in value}
    for key, field in [('input_tokens_details', 'cached_tokens'), ('output_tokens_details', 'reasoning_tokens')]:
        detail = value.get(key)
        if isinstance(detail, dict) and field in detail:
            safe[key] = {field: number(detail[field])}
    return safe


def command_id(value, ordinal):
    # Codex IDs are opaque item_N identifiers, never arbitrary command/source strings.
    return value if isinstance(value, str) and re.fullmatch(r'item_\d+', value) else f'command_{ordinal}'


def telemetry(path):
    commands, mcp = {}, {'item.started': set(), 'item.completed': set()}
    counts = dict(thread_starts=0, turn_starts=0, usage_events=0, structured_context_length_exceeded=0,
                  invalid_json_lines=0)
    aggregates = []
    context = dict.fromkeys(CONTEXT_FIELDS)
    with path.open() as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except ValueError:
                counts['invalid_json_lines'] += 1
                continue
            if not isinstance(event, dict):
                continue
            kind = event.get('type')
            if kind == 'thread.started': counts['thread_starts'] += 1
            if kind == 'turn.started': counts['turn_starts'] += 1
            if isinstance(event.get('usage'), dict):
                counts['usage_events'] += 1
                if kind == 'turn.completed': aggregates.append(usage(event['usage']))
            error = event.get('error')
            if kind in ('context_length_exceeded', 'error.context_length_exceeded') or (
                    isinstance(error, dict) and error.get('code') == 'context_length_exceeded'):
                counts['structured_context_length_exceeded'] += 1
            # Only this explicit typed schema supplies context measurements. No text scanning.
            if kind == 'context.telemetry':
                for key in CONTEXT_FIELDS:
                    value = number(event.get(key))
                    if value is not None: context[key] = value
            item = event.get('item')
            if not isinstance(item, dict) or not isinstance(item.get('id'), str):
                continue
            key = item['id']
            if item.get('type') == 'command_execution' and kind == 'item.completed':
                code = integer(item.get('exit_code'))
                previous = commands.get(key)
                failed = code not in (None, 0) or item.get('status') == 'failed'
                if previous is None or failed:
                    commands[key] = dict(exit_code=code, failed=failed)
            if item.get('type') == 'mcp_tool_call' and kind in mcp:
                mcp[kind].add(key)
    failures = [dict(id=command_id(key, i), exit_code=value['exit_code'])
                for i, (key, value) in enumerate(commands.items(), 1) if value['failed']]
    return dict(**counts, unique_completed_commands=len(commands), failed_commands=failures,
                mcp_started=len(mcp['item.started']), mcp_completed=len(mcp['item.completed']),
                unique_mcp_items=len(mcp['item.started'] | mcp['item.completed']),
                raw_aggregate_usage=aggregates,
                last_session_aggregate_usage=aggregates[-1] if aggregates else None,
                context=context)


def reviews(manual):
    result = []
    entries = manual.get('pages', [])
    for lane in LANES:
        for page in (1, 2, 3):
            matches = [row for row in entries if isinstance(row, dict) and row.get('lane') == lane
                       and type(row.get('page')) is int and row['page'] == page]
            if len(matches) > 1:
                raise ValueError('duplicate manual page review')
            row = matches[0] if matches else {}
            safe = dict(lane=lane, page=page, accepted_seconds=None)
            for key in REVIEW_FIELDS:
                value = row.get(key)
                safe[key] = value if value in VERDICTS else None
            value = row.get('unsupported_content')
            safe['unsupported_content'] = value if value in (
                'not_observed_in_reviewed_scope', 'observed') else None
            safe['omission_codes'] = sorted({code if isinstance(code, str) and code in OMISSION_CODES
                                             else 'OTHER' for code in row.get('omission_codes', [])})
            result.append(safe)
    return result


def evaluation_rows(evaluations):
    result = []
    for row in evaluations:
        if not isinstance(row, dict) or row.get('lane') not in LANES or type(row.get('page')) is not int or row['page'] not in (1, 2, 3):
            continue
        if row.get('viewport') not in ('1280x900', '390x844'):
            continue
        result.append(dict(lane=row['lane'], page=row['page'], viewport=row['viewport'],
                           functional_passed=row.get('functional_passed') if type(row.get('functional_passed')) is bool else None,
                           browser_errors=number(row.get('browser_errors')),
                           diagnostic_rgb_mae_fraction=number(row.get('diagnostic_rgb_mae_fraction')),
                           accepted_seconds=None))
    return result


def render(data):
    lines = ['# Pós-coleta iPede', '', f'Contrato: {CONTRACT}. Rodada: {ROUND}.', '',
             'Hipótese causal: **INCONCLUSIVO**. Uma tentativa por lane; retries internos indisponíveis.', '',
             '## Revisão por página', '',
             '| Lane | ID | Fidelidade visual | Conteúdo | Estado | Funcionalidade no escopo | Omissões | Conteúdo sem suporte |',
             '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for row in data['pages']:
        values = [row[key] or 'indisponível' for key in REVIEW_FIELDS]
        lines.append(f"| {row['lane']} | {row['page']} | {values[0]} | {values[2]} | {values[1]} | {values[3]} | {', '.join(row['omission_codes']) or 'nenhum código registrado'} | {row['unsupported_content'] or 'indisponível'} |")
    lines += ['', '## Tempo, tokens e ferramentas', '',
              'Fonte de telemetria: raw JSONL (evidence/events.jsonl de cada lane). Contagens MCP por ID único em cada fase; iniciado e concluído não são duas chamadas.', '']
    for lane, run in data['runs'].items():
        t = run['telemetry']
        u = t['last_session_aggregate_usage'] or {}
        lines.append(f"- {lane}: MCP configurado {'sim' if run['mcp_configured'] else 'não'}; iniciado {t['mcp_started']}, concluído {t['mcp_completed']}. Comandos concluídos {t['unique_completed_commands']}, falhos {len(t['failed_commands'])}. Tempo agente {run['seconds']} s; total {run['total_seconds']} s; índice frio {run['cold_index_seconds']} s. Último agregado: input {u.get('input_tokens')}, output {u.get('output_tokens')}. Erros estruturados de contexto: {t['structured_context_length_exceeded']}.")
    lines += ['', 'Detalhes numéricos, snapshots agregados, cache/reasoning e falhas de comandos estão em data.json. null significa indisponível; não há tokens por página nem conversão em dinheiro.', '',
              '## Contexto', '', '| Lane | Maior contexto real | Tokens por chamada | Limite backend | Compactions | Resets | Truncations |',
              '| --- | --- | --- | --- | --- | --- | --- |']
    for lane, run in data['runs'].items():
        values = [str(run['telemetry']['context'][key]) if run['telemetry']['context'][key] is not None else 'indisponível' for key in CONTEXT_FIELDS]
        lines.append('| '+lane+' | '+' | '.join(values)+' |')
    observation = data['model_context_observation']
    lines += ['', 'Configuração anunciada (cache, não medição do backend): '+json.dumps(observation, ensure_ascii=False)+'.', '', '## Limitações', '']
    lines += ['- '+item for item in LIMITATIONS]
    return '\n'.join(lines)+'\n'


def posthoc(root):
    root = root_path(root)
    runs = json.loads((root/'run-results.private.json').read_text())
    evaluations = json.loads((root/'evaluation-results.private.json').read_text())
    manual_path = root/'manual-findings.private.json'
    manual = json.loads(manual_path.read_text()) if manual_path.exists() else {}
    observation_path = root/'model-context-observation.private.json'
    observation = json.loads(observation_path.read_text()) if observation_path.exists() else {}
    advertised = {key: number(observation.get(key)) for key in OBSERVATION_FIELDS}
    policy = observation.get('advertised_tool_output_truncation_policy', {})
    advertised['advertised_tool_output_truncation_limit'] = number(policy.get('limit')) if isinstance(policy, dict) else None
    safe_runs = {}
    for lane in LANES:
        run = runs[lane]
        safe_runs[lane] = dict(attempts=1, provider_internal_retries=None, mcp_configured=lane == 'B',
                               **{key: number(run.get(key)) for key in ('seconds', 'total_seconds', 'cold_index_seconds')},
                               exit_code=integer(run.get('exit_code')), money=None,
                               telemetry=telemetry(root/'runs'/lane/'evidence'/'events.jsonl'))
    data = dict(contract=CONTRACT, round=ROUND, samples_per_condition=1, hypothesis_verdict='INCONCLUSIVO',
                manual_review_present=manual_path.exists(), pages=reviews(manual),
                evaluation=evaluation_rows(evaluations), runs=safe_runs,
                model_context_observation=advertised, limitations=LIMITATIONS)
    out = fresh(root/'posthoc')
    write_json(out/'data.json', data)
    (out/'report.md').write_text(render(data))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scratch', required=True)
    args = parser.parse_args()
    posthoc(args.scratch)


if __name__ == '__main__':
    main()
