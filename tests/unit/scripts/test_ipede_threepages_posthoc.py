"""Synthetic post-collection fixtures only; no agents, browser or private inputs."""
import json
import subprocess
from pathlib import Path
import sys

import pytest

from scripts.ipede_threepages.common import write_json
from scripts.ipede_threepages.posthoc import posthoc, telemetry


PRIVATE = 'CLIENT_SECRET /private/customer/page-name'


def event(kind, item_id='item_1', item_type='command_execution', **fields):
    return dict(type=kind, item=dict(id=item_id, type=item_type, **fields))


def fixture(root, events=None, manual=True):
    write_json(root/'run-results.private.json', {
        lane: dict(seconds=12, total_seconds=15, cold_index_seconds=3, exit_code=0,
                   raw_usage=[{'input_tokens':999999}], private_notes=PRIVATE)
        for lane in ('A', 'B')})
    write_json(root/'evaluation-results.private.json', [dict(
        lane='A', page=1, viewport='1280x900', functional_passed=True, browser_errors=0,
        diagnostic_rgb_mae_fraction=.3, accepted_seconds=2, page_name=PRIVATE, source=PRIVATE)])
    write_json(root/'model-context-observation.private.json', dict(
        advertised_context_window_tokens=500000, advertised_effective_context_window_percent=95,
        calculated_effective_context_window_tokens=475000,
        advertised_tool_output_truncation_policy={'mode':PRIVATE, 'limit':10000},
        server_enforced_context_limit=999999, source=PRIVATE, private_report=PRIVATE))
    if manual:
        write_json(root/'manual-findings.private.json', dict(
            pages=[dict(lane=lane, page=page, visual_verdict='FAIL', state_verdict='PASS',
                        content_verdict='FAIL', functional_scope_verdict='PASS',
                        unsupported_content='observed', omission_codes=['CONTENT', PRIVATE],
                        private_notes=PRIVATE, page_name=PRIVATE, accepted_seconds=5)
                   for lane in ('A','B') for page in (1,2,3)],
            hypothesis_verdict='PASS', private_report=PRIVATE))
    for lane in ('A', 'B'):
        evidence = root/'runs'/lane/'evidence'
        evidence.mkdir(parents=True)
        (evidence/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in (events or [])))
    return root


def read(out):
    return json.loads((out/'data.json').read_text())


def test_started_completed_duplicates_do_not_duplicate_tools(tmp_path):
    events = [event(kind) for kind in ('item.started','item.started','item.completed','item.completed')]
    events += [event(kind, 'item_2', 'mcp_tool_call')
               for kind in ('item.started','item.started','item.completed','item.completed')]
    fixture(tmp_path, events)
    t = read(posthoc(tmp_path))['runs']['A']['telemetry']
    assert t['unique_completed_commands'] == 1
    assert t['mcp_started'] == t['mcp_completed'] == t['unique_mcp_items'] == 1


def test_missing_per_call_is_null_and_zero_errors_is_stream_only(tmp_path):
    fixture(tmp_path, [dict(type='thread.started'), dict(type='turn.started')])
    data = read(posthoc(tmp_path))
    t = data['runs']['B']['telemetry']
    assert all(value is None for value in t['context'].values())
    assert t['last_session_aggregate_usage'] is None
    assert t['thread_starts'] == t['turn_starts'] == 1
    assert t['structured_context_length_exceeded'] == 0
    assert any('não prova ausência' in text for text in data['limitations'])


def test_source_text_does_not_trigger_context_or_truncation(tmp_path):
    fixture(tmp_path, [event('item.completed', command='context_length_exceeded truncation_count=3',
                             aggregated_output='context_length_exceeded', source='reset_count=5'),
                       dict(type='item.completed', item={'type':'agent_message', 'text':'context_length_exceeded'})])
    t = read(posthoc(tmp_path))['runs']['A']['telemetry']
    assert t['structured_context_length_exceeded'] == 0
    assert t['context']['truncation_count'] is None
    assert t['context']['reset_count'] is None


def test_only_structured_error_fields_are_counted(tmp_path):
    fixture(tmp_path, [dict(type='context_length_exceeded'),
                       dict(type='error', error={'code':'context_length_exceeded', 'message':PRIVATE}),
                       dict(type='error.context_length_exceeded', error={'code':'context_length_exceeded'}),
                       dict(type='error', error='context_length_exceeded'),
                       dict(type='error', code='context_length_exceeded')])
    assert read(posthoc(tmp_path))['runs']['A']['telemetry']['structured_context_length_exceeded'] == 3


def test_usage_snapshots_cache_and_reasoning_are_never_added(tmp_path):
    usage = dict(input_tokens=100, cached_input_tokens=80, output_tokens=20,
                 reasoning_output_tokens=12, private_notes=PRIVATE,
                 input_tokens_details={'cached_tokens':80, 'source':PRIVATE},
                 output_tokens_details={'reasoning_tokens':12, 'source':PRIVATE})
    fixture(tmp_path, [dict(type='turn.completed', usage={'input_tokens':50, 'output_tokens':10}),
                       dict(type='turn.completed', usage=usage)])
    t = read(posthoc(tmp_path))['runs']['A']['telemetry']
    assert t['usage_events'] == 2 and len(t['raw_aggregate_usage']) == 2
    last = t['last_session_aggregate_usage']
    assert last['input_tokens'] == 100 and last['output_tokens'] == 20
    assert last['cached_input_tokens'] == last['input_tokens_details']['cached_tokens'] == 80
    assert last['reasoning_output_tokens'] == 12
    assert 'private_notes' not in last


def test_private_strings_never_leave_allowlist_and_acceptance_is_null(tmp_path):
    fixture(tmp_path, [event('item.completed', command=PRIVATE, aggregated_output=PRIVATE)])
    out = posthoc(tmp_path)
    data = read(out)
    for path in out.iterdir():
        text = path.read_text()
        assert PRIVATE not in text and '/private/customer' not in text
        assert 'private_notes' not in text and 'private_report' not in text
    assert data['contract'] == 'benchmark-ipede-v2' and data['round'] == 'iPede-3pages-v3'
    assert all(row['accepted_seconds'] is None for row in data['pages']+data['evaluation'])
    assert all(row['omission_codes'] == ['CONTENT','OTHER'] for row in data['pages'])
    assert data['model_context_observation'] == dict(
        advertised_context_window_tokens=500000, advertised_effective_context_window_percent=95,
        calculated_effective_context_window_tokens=475000, advertised_tool_output_truncation_limit=10000)
    report = (out/'report.md').read_text()
    assert 'não percentual de precisão' in report and 'não prova alucinação' in report
    assert 'evidence/events.jsonl' in report


def test_b_zero_mcp_causality_inconclusive_even_if_manual_says_pass(tmp_path):
    fixture(tmp_path)
    data = read(posthoc(tmp_path))
    assert data['runs']['B']['mcp_configured'] is True
    assert data['runs']['B']['telemetry']['unique_mcp_items'] == 0
    assert data['hypothesis_verdict'] == 'INCONCLUSIVO'
    assert all(run['attempts'] == 1 and run['provider_internal_retries'] is None
               and run['money'] is None for run in data['runs'].values())
    assert any('offsets' in line and 'viola' in line for line in data['limitations'])


def test_failed_command_ids_and_exits_preserved_without_commands(tmp_path):
    events = [event('item.completed', 'item_7', exit_code=2, command=PRIVATE, aggregated_output=PRIVATE),
              event('item.completed', 'item_7', exit_code=2),
              event('item.completed', 'item_8', exit_code=-9),
              event('item.completed', 'item_9', status='failed'),
              event('item.completed', PRIVATE, exit_code=1),
              event('item.completed', 'item_10', exit_code=0)]
    fixture(tmp_path, events)
    t = read(posthoc(tmp_path))['runs']['A']['telemetry']
    assert t['unique_completed_commands'] == 5
    assert t['failed_commands'] == [dict(id='item_7',exit_code=2), dict(id='item_8',exit_code=-9),
                                    dict(id='item_9',exit_code=None), dict(id='command_4',exit_code=1)]


def test_fresh_refuses_overwrite(tmp_path):
    fixture(tmp_path)
    out = posthoc(tmp_path)
    before = {p.name:p.read_bytes() for p in out.iterdir()}
    with pytest.raises(FileExistsError):
        posthoc(tmp_path)
    assert before == {p.name:p.read_bytes() for p in out.iterdir()}


def test_optional_review_missing_and_typed_context(tmp_path):
    fixture(tmp_path, [dict(type='context.telemetry', largest_observed_context_tokens=300,
                            backend_context_limit=500, compaction_count=0, reset_count=1,
                            truncation_count=2, tokens_per_call=40)], manual=False)
    data = read(posthoc(tmp_path))
    assert data['manual_review_present'] is False
    assert all(row['visual_verdict'] is None for row in data['pages'])
    assert data['runs']['A']['telemetry']['context'] == dict(
        largest_observed_context_tokens=300, backend_context_limit=500, compaction_count=0,
        reset_count=1, truncation_count=2, tokens_per_call=40)


def test_module_cli_synthetic_only(tmp_path):
    fixture(tmp_path)
    result = subprocess.run([sys.executable, '-m', 'scripts.ipede_threepages.posthoc', '--scratch', str(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (tmp_path/'posthoc'/'report.md').is_file()
