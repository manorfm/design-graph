"""Synthetic protocol tests; never launch Codex or installed MCP/indexer."""
import base64
import json
import os
from pathlib import Path
import sys

import pytest

from scripts.ipede_threepages.common import digest, fresh, hashes, write_json
from scripts.ipede_threepages import preflight as gate
from scripts.ipede_threepages.runner import command, execute, run


def proof(folder):
    folder.mkdir()
    write_json(folder/'metrics.json', dict(stop_reason=None, exit_code=0))
    (folder/'stderr.log').write_text('')
    (folder/'server-stderr.log').write_text('')
    catalogue = [dict(name='inspect', inputSchema=dict(type='object'))]
    messages = [
        ('client', dict(id=1, method='initialize')),
        ('server', dict(id=1, result=dict(serverInfo=dict(name='test')))),
        ('client', dict(method='notifications/initialized')),
        ('client', dict(id=2, method='tools/list')),
        ('server', dict(id=2, result=dict(tools=catalogue))),
        ('client', dict(id=3, method='tools/call', params=dict(name='inspect', arguments={}))),
        ('server', dict(id=3, result=dict(content=[dict(type='text', text='Neutral Observatory')]))),
    ]
    (folder/'transcript.jsonl').write_text(''.join(json.dumps(dict(direction=d, bytes=base64.b64encode((json.dumps(m)+'\n').encode()).decode()))+'\n' for d,m in messages))
    events = [dict(type='item.completed', item=dict(type='mcp_tool_call', server='design-graph', tool='inspect',
               status='completed', arguments={}, result=dict(content=[dict(type='text', text='Neutral Observatory')]))),
              dict(type='turn.completed')]
    (folder/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
    return catalogue


def test_neutral_heading_must_come_from_non_listing_native_result(tmp_path):
    folder=tmp_path/'proof'; proof(folder)
    assert gate.evidence(folder, required_text='Neutral Observatory')
    with pytest.raises(ValueError, match='no successful native'):
        gate.evidence(folder, required_text='Absent heading')
    for name in ('transcript.jsonl', 'events.jsonl'):
        if name == 'events.jsonl':
            (folder/name).write_text((folder/name).read_text().replace('inspect','list_screens'))
        else:
            records=[json.loads(line) for line in (folder/name).read_text().splitlines()]
            for record in records:
                record['bytes']=base64.b64encode(base64.b64decode(record['bytes']).replace(b'inspect',b'list_screens')).decode()
            (folder/name).write_text(''.join(json.dumps(r)+'\n' for r in records))
    with pytest.raises(ValueError, match='no successful native'):
        gate.evidence(folder, required_text='Neutral Observatory')


def test_guard_does_not_confuse_source_vocabulary_with_actual_refusal():
    from scripts.ipede_threepages.runner import guard_refusal
    assert not guard_refusal("promise.status = 'rejected'; const denied = false; console.error('unknown');")
    assert guard_refusal('Command rejected by policy')
    assert guard_refusal('Permission denied')
    assert guard_refusal('Operation not permitted')


def test_native_event_and_actual_transcript_both_required(tmp_path):
    folder=tmp_path/'proof'; catalogue=proof(folder)
    assert gate.evidence(folder)==catalogue
    transcript=(folder/'transcript.jsonl').read_text()
    (folder/'transcript.jsonl').write_text('')
    with pytest.raises(ValueError): gate.evidence(folder)
    (folder/'transcript.jsonl').write_text(transcript)
    (folder/'events.jsonl').write_text(json.dumps(dict(type='turn.completed', synthetic_mcp_success=True))+'\n')
    with pytest.raises(ValueError, match='no successful native'): gate.evidence(folder)


@pytest.mark.parametrize('change', ['failed', 'timeout', 'refused', 'call_error', 'mismatch', 'missing_list', 'not_completed'])
def test_gate_fails_closed_on_incomplete_or_failed_evidence(tmp_path, change):
    folder=tmp_path/'proof';proof(folder)
    if change in {'failed','timeout'}:
        write_json(folder/'metrics.json', dict(stop_reason='timeout' if change=='timeout' else None, exit_code=1))
    elif change=='refused':
        (folder/'stderr.log').write_text('Command rejected by policy')
    elif change=='missing_list':
        records=[json.loads(line) for line in (folder/'transcript.jsonl').read_text().splitlines()]
        records=[r for r in records if b'tools/list' not in base64.b64decode(r['bytes'])]
        (folder/'transcript.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
    else:
        events=[json.loads(line) for line in (folder/'events.jsonl').read_text().splitlines()]
        item=events[0]['item']
        if change=='call_error': item['error']='failed'
        if change=='mismatch': item['arguments']={'fabricated':True}
        if change=='not_completed': item['status']='failed'
        (folder/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
    with pytest.raises(ValueError): gate.evidence(folder)


@pytest.mark.parametrize('state', ['missing', 'failed', 'no_transcript', 'identity_changed'])
def test_run_gate_prevents_all_launches_and_runs_directory(tmp_path, monkeypatch, state):
    prep=fresh(tmp_path/'preparation')
    write_json(prep/'environment.json', dict(python=sys.executable, worktree=str(tmp_path)))
    write_json(prep/'freeze.json', dict(files={}))
    approval=tmp_path/'approval.json'
    write_json(approval, dict(approved=True, freeze_sha256=digest(prep/'freeze.json'), scope_decision='test'))
    monkeypatch.setattr(gate, 'identity', lambda *a: {'sha256':'current'})
    if state!='missing':
        folder=fresh(tmp_path/'preflight-v4');catalogue=proof(folder/'evidence')
        write_json(folder/'evidence/catalogue.json',catalogue)
        if state=='no_transcript': (folder/'evidence/transcript.jsonl').write_text('')
        write_json(folder/'gate.json', dict(protocol=gate.PROTOCOL, success=state!='failed',
                   identity={'sha256':'changed' if state=='identity_changed' else 'current'}, evidence_hashes=hashes(folder/'evidence')))
    def forbidden(*a, **kw): pytest.fail('gate failure must prevent every subprocess launch')
    monkeypatch.setattr('subprocess.Popen', forbidden)
    with pytest.raises(ValueError, match='successful v4 preflight required'): run(tmp_path,approval)
    assert not (tmp_path/'runs').exists()


def test_guard_stops_before_equivalent_action(tmp_path):
    work=fresh(tmp_path/'work');evidence=fresh(tmp_path/'evidence')
    script=tmp_path/'guard.py'
    script.write_text("import sys,time\nfrom pathlib import Path\nprint('Command rejected by policy',file=sys.stderr,flush=True)\ntime.sleep(1)\nPath('alternate-api-action').write_text('should never happen')\n")
    result=execute([sys.executable,str(script)],work,evidence,'',os.environ.copy(),seconds=3)
    assert result['stop_reason']=='guard_refusal'
    assert not (work/'alternate-api-action').exists()
    assert 'rejected by policy' in (evidence/'stderr.log').read_text()


def test_preflight_uses_shared_model_command_limits_and_real_server(tmp_path, monkeypatch):
    monkeypatch.setattr(gate,'identity',lambda *args: {'sha256':'test'})
    indexed=[];calls=[]
    class Index:
        pid=99999999
        returncode=0
        def __init__(self, argv, **kw): indexed.append(argv)
        def wait(self, **kw): return 0
    monkeypatch.setattr(gate.subprocess,'Popen',Index)
    monkeypatch.setattr(gate,'cleanup',lambda p: None)
    def executor(argv,work,evidence,prompt,env,seconds,limit):
        calls.append((argv,seconds,limit))
        # Leave missing native evidence: even a synthetic "success" cannot pass.
        write_json(evidence/'metrics.json',dict(stop_reason=None,exit_code=0))
        (evidence/'stderr.log').write_text('')
        (evidence/'server-stderr.log').write_text('')
        (evidence/'events.jsonl').write_text('{"success":true}\n')
        (evidence/'transcript.jsonl').write_text('')
    monkeypatch.setattr(gate,'execute',executor)
    with pytest.raises(ValueError): gate.preflight(tmp_path,Path(sys.executable),Path.cwd())
    assert indexed[0][1].endswith('/neutral.html')
    argv,seconds,limit=calls[0]
    assert seconds==900 and limit==90
    assert argv[:10]==command(Path('work'),Path('state'))[:10]
    assert any('stdio_recorder.py' in arg for arg in argv)
    assert 'Neutral Observatory' in (tmp_path/'preflight-v4/work/neutral.html').read_text()
    assert json.loads((tmp_path/'preflight-v4/gate.json').read_text())['success'] is False


def test_successful_gate_is_rechecked_and_tampering_rejected(tmp_path, monkeypatch):
    folder=fresh(tmp_path/'preflight-v4');catalogue=proof(folder/'evidence')
    write_json(folder/'evidence/catalogue.json',catalogue)
    monkeypatch.setattr(gate,'identity',lambda *a: {'sha256':'current'})
    write_json(folder/'gate.json',dict(protocol=gate.PROTOCOL,success=True,identity={'sha256':'current'},
               evidence_hashes=hashes(folder/'evidence')))
    gate.validate_gate(tmp_path,Path(sys.executable),tmp_path)
    (folder/'evidence/events.jsonl').write_text('{"synthetic_success":true}\n')
    with pytest.raises(ValueError,match='evidence changed'):
        gate.validate_gate(tmp_path,Path(sys.executable),tmp_path)


def test_cli_preserves_virtualenv_python_symlink(tmp_path, monkeypatch):
    from scripts.ipede_threepages import __main__ as cli
    bindir=fresh(tmp_path/'venv/bin')
    python=bindir/'python';python.symlink_to(sys.executable)
    captured=[]
    monkeypatch.setattr(sys,'argv',['ipede','preflight','--scratch',str(tmp_path),'--python',str(python)])
    monkeypatch.setattr(cli,'environment',lambda root: {})
    monkeypatch.setattr(cli.os,'umask',lambda mode: None)
    monkeypatch.setattr(gate,'preflight',lambda root, interpreter, worktree: captured.append(interpreter))
    cli.main()
    assert captured==[python]
    assert captured[0].parent==bindir
