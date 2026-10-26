"""Synthetic B-only tests; no collection, preflight or real indexer."""
import base64
import json
import os
from pathlib import Path
import sys

import pytest

from scripts.ipede_threepages import b_v4, preflight
from scripts.ipede_threepages.common import digest, fresh, hashes, write_json
from scripts.ipede_threepages.native_audit import covered_screens
from scripts.ipede_threepages.runner import command, execute


SELECTION = [dict(key=k, label=k.title(), component=k.title()+'Page') for k in ['alpha','beta','gamma']]


def baseline(root):
    prep=fresh(root/'preparation'); agent=fresh(prep/'agent-input')
    fresh(agent/'input'); (agent/'input/full.js').write_text('entire source')
    write_json(agent/'selection.json', SELECTION)
    (prep/'original.html').write_text('integral wrapper and resources')
    (prep/'prompt.txt').write_bytes(b'UNCHANGED baseline extraction/copy prompt\n')
    write_json(prep/'freeze.json', dict(files=hashes(prep), input_hashes=hashes(agent), instrument_hashes={'old.py':'old'}))
    evidence=fresh(root/'runs/A/evidence'); (evidence/'events.jsonl').write_text('inherited A')
    return root


def native_proof(folder, count=3, tool='get_screen', empty=False, mismatch=False):
    catalogue=dict(id=99,result=dict(tools=[dict(name=tool)]))
    records=[dict(direction='server',bytes=base64.b64encode((json.dumps(catalogue)+'\n').encode()).decode())];events=[]
    for i, screen in enumerate(SELECTION[:count], 1):
        args=dict(name=screen['component'])
        text=screen['component'] + (' no data' if empty else '\n## Components\n### Table\nSource: function render(){ return <main><button>Filter</button></main>; }')
        content=[dict(type='text',text=text)]
        request=dict(id=i,method='tools/call',params=dict(name=tool,arguments=args))
        response=dict(id=i,result=dict(content=content))
        for direction,message in [('client',request),('server',response)]:
            records.append(dict(direction=direction,bytes=base64.b64encode((json.dumps(message)+'\n').encode()).decode()))
        events.append(dict(type='item.completed',item=dict(type='mcp_tool_call',server='design-graph',tool=tool,
                      arguments={} if mismatch else args,status='completed',result=dict(content=content))))
    (folder/'transcript.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
    (folder/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))


@pytest.mark.parametrize('count,tool,empty,mismatch,expected', [
    (3,'get_screen',False,False,{1,2,3}), (2,'get_screen',False,False,{1,2}),
    (3,'list_screens',False,False,set()), (3,'get_screen',True,False,set()),
    (3,'get_screen',False,True,set())])
def test_three_real_relevant_queries_required(tmp_path,count,tool,empty,mismatch,expected):
    native_proof(tmp_path,count,tool,empty,mismatch)
    assert covered_screens(tmp_path,SELECTION)==expected


def test_unrelated_arguments_and_diagnostic_responses_do_not_cover_screen(tmp_path):
    native_proof(tmp_path)
    data=(tmp_path/'transcript.jsonl').read_text()
    events=(tmp_path/'events.jsonl').read_text()
    (tmp_path/'events.jsonl').write_text(events.replace('AlphaPage','Unrelated'))
    assert covered_screens(tmp_path,SELECTION)=={2,3}
    native_proof(tmp_path)
    records=[json.loads(line) for line in (tmp_path/'transcript.jsonl').read_text().splitlines()]
    for r in records:
        raw=base64.b64decode(r['bytes']).decode().replace('## Components','Screen not found. ## Components')
        r['bytes']=base64.b64encode(raw.encode()).decode()
    (tmp_path/'transcript.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
    (tmp_path/'events.jsonl').write_text(events.replace('## Components','Screen not found. ## Components'))
    assert covered_screens(tmp_path,SELECTION)==set()


def test_b_refuses_before_gate_without_launch_or_runs(tmp_path,monkeypatch):
    root=fresh(tmp_path/'v4'); old=baseline(fresh(tmp_path/'v3')); before=hashes(old)
    monkeypatch.setattr(preflight,'validate_gate',lambda *a: (_ for _ in ()).throw(ValueError('gate required')))
    monkeypatch.setattr('subprocess.Popen',lambda *a,**kw: pytest.fail('no process before gate'))
    with pytest.raises(ValueError,match='gate required'): b_v4.run_b_v4(root,old,Path(sys.executable),Path.cwd())
    assert not (root/'runs').exists() and hashes(old)==before


def test_live_output_gate_stops_before_alternative_action(tmp_path):
    work=fresh(tmp_path/'work'); fresh(work/'output'); evidence=fresh(tmp_path/'evidence')
    script=tmp_path/'early.py'
    script.write_text("from pathlib import Path\nimport time\nPath('output/page-1.html').write_text('early')\ntime.sleep(1)\nPath('alternate').write_text('bad')\n")
    result=execute([sys.executable,str(script)],work,evidence,'',os.environ.copy(),seconds=3,selections=SELECTION)
    assert result['stop_reason']=='output_before_screen_queries'
    assert not (work/'alternate').exists()


def test_index_before_session_baseline_preserved_and_separate_timing(tmp_path,monkeypatch):
    root=fresh(tmp_path/'v4'); old=baseline(fresh(tmp_path/'v3')); before=hashes(old)
    order=[]; calls=[]
    monkeypatch.setattr(preflight,'validate_gate',lambda *a: order.append('gate'))
    monkeypatch.setattr(preflight,'identity',lambda *a: {'frozen':'test'})
    monkeypatch.setattr(preflight,'evidence',lambda *a: [])
    monkeypatch.setattr(b_v4,'graph_ready',lambda *a: {'ready':True})
    class Index:
        def __init__(self,argv,**kw):
            order.append('index');calls.append(argv)
            assert argv[1]==str(old/'preparation/original.html')
        def wait(self,**kw): return 0
    monkeypatch.setattr(b_v4.subprocess,'Popen',Index)
    monkeypatch.setattr(b_v4,'cleanup',lambda p: None)
    def session(argv,work,proof,prompt,env,**kw):
        order.append('session');calls.append(argv)
        assert prompt==(old/'preparation/prompt.txt').read_text()+b_v4.CONDITION
        assert hashes(work/'input')==hashes(old/'preparation/agent-input/input')
        assert kw==dict(seconds=900,limit=90,selections=SELECTION)
        native_proof(proof)
        for i in range(1,4): (work/'output'/f'page-{i}.html').write_text('output')
        return dict(seconds=7,stop_reason=None,exit_code=0,queried_screen_indexes=[1,2,3])
    monkeypatch.setattr(b_v4,'execute',session)
    result=b_v4.run_b_v4(root,old,Path(sys.executable),Path.cwd())
    assert order==['gate','index','session'] and hashes(old)==before
    assert result['seconds']==7 and result['postprocessing_seconds']>=0 and result['setup_index_seconds']>=0
    assert not (root/'runs/A').exists()
    assert digest(root/'runs/B/prompt.txt')==digest(old/'preparation/prompt.txt')
    assert any('stdio_recorder.py' in arg for arg in calls[1])
    with pytest.raises(ValueError,match="no retry"): b_v4.run_b_v4(root,old,Path(sys.executable),Path.cwd())


def test_frozen_manifest_only_not_historical_instrument(tmp_path):
    old=baseline(tmp_path)
    assert b_v4.verify_baseline(old)['historical_instrument_hashes']=={'old.py':'old'}
    (old/'preparation/agent-input/input/full.js').write_text('changed')
    with pytest.raises(ValueError,match='frozen file manifest'): b_v4.verify_baseline(old)


def test_disable_inherited_mcps_without_ignoring_policy(tmp_path,monkeypatch):
    home=fresh(tmp_path/'home');monkeypatch.setenv('CODEX_HOME',str(home))
    (home/'config.toml').write_text('[mcp_servers.extra]\ncommand="extra"\n[profiles.x.mcp_servers.other]\ncommand="other"\n')
    argv=command(tmp_path,tmp_path/'state',dict(command='/server',pythonpath='/src',graph='/graph'))
    assert 'mcp_servers.extra.enabled=false' in argv and 'mcp_servers.other.enabled=false' in argv
    assert 'mcp_servers.design-graph.enabled=true' in argv
    assert not any(arg.startswith('--ignore-') or 'bypass' in arg for arg in argv)


@pytest.mark.parametrize('missing,refused', [(True,False),(False,True)])
def test_b_missing_screen_or_guard_retains_invalid_result(tmp_path,monkeypatch,missing,refused):
    root=fresh(tmp_path/'v4');old=baseline(fresh(tmp_path/'v3'));before=hashes(old)
    monkeypatch.setattr(preflight,'validate_gate',lambda *a: None)
    monkeypatch.setattr(preflight,'identity',lambda *a: {})
    monkeypatch.setattr(preflight,'evidence',lambda *a: [])
    monkeypatch.setattr(b_v4,'graph_ready',lambda *a: {'ready':True})
    class Index:
        def __init__(self,*a,**kw): pass
        def wait(self,**kw): return 0
    monkeypatch.setattr(b_v4.subprocess,'Popen',Index)
    monkeypatch.setattr(b_v4,'cleanup',lambda p: None)
    def session(argv,work,proof,*a,**kw):
        native_proof(proof,2 if missing else 3)
        return dict(seconds=1,exit_code=0,stop_reason='guard_refusal' if refused else None,
                    queried_screen_indexes=[1,2] if missing else [1,2,3])
    monkeypatch.setattr(b_v4,'execute',session)
    with pytest.raises(ValueError): b_v4.run_b_v4(root,old,Path(sys.executable),Path.cwd())
    result=json.loads((root/'run-results-v4.private.json').read_text())
    assert result['B']['valid'] is False and hashes(old)==before
    assert not (root/'runs/A').exists()


def test_live_gate_allows_output_after_three_matched_calls(tmp_path):
    work=fresh(tmp_path/'work');fresh(work/'output');evidence=fresh(tmp_path/'evidence')
    fixture=fresh(tmp_path/'fixture');native_proof(fixture)
    # RPC exists first; native completions must be received before output is allowed.
    (evidence/'transcript.jsonl').write_bytes((fixture/'transcript.jsonl').read_bytes())
    script=tmp_path/'late.py'
    script.write_text("from pathlib import Path\nimport time\n"+
                      f"print({(fixture/'events.jsonl').read_text()!r},flush=True)\n"+
                      "time.sleep(.2)\nPath('output/page-1.html').write_text('after queries')\n")
    result=execute([sys.executable,str(script)],work,evidence,'',os.environ.copy(),seconds=3,selections=SELECTION)
    assert result['stop_reason'] is None and result['queried_screen_indexes']==[1,2,3]


def test_proxy_identity_binds_real_binary_and_full_recorder_shape(tmp_path,monkeypatch):
    import scripts.ipede_threepages.runner as runner
    launcher=tmp_path/'codex';launcher.write_bytes(b'fake native binary')
    monkeypatch.setattr(preflight.shutil,'which',lambda name: str(launcher))
    monkeypatch.setattr(runner,'inherited_servers',lambda cwd: [])
    identity=preflight.identity(Path(sys.executable),Path.cwd(),tmp_path)
    payload=identity['payload']
    assert payload['real_binary']==str(launcher)
    assert payload['files'][str(launcher)]==digest(launcher)
    assert any('stdio_recorder.py' in arg and '<evidence>' in arg and 'design-mcp' in arg for arg in payload['command'])


def test_cli_rejects_baseline_scratch_overlap_before_environment_mutation(tmp_path,monkeypatch):
    from scripts.ipede_threepages import __main__ as cli
    monkeypatch.setattr(sys,'argv',['ipede','run-b-v4','--scratch',str(tmp_path),'--baseline',str(tmp_path),'--python',sys.executable])
    monkeypatch.setattr(cli,'environment',lambda *a: pytest.fail('must not write baseline'))
    with pytest.raises(SystemExit): cli.main()


def test_source_error_identifier_does_not_invalidate_substantive_native_result(tmp_path):
    native_proof(tmp_path)
    for name in ('events.jsonl', 'transcript.jsonl'):
        if name == 'events.jsonl':
            (tmp_path/name).write_text((tmp_path/name).read_text().replace('Filter', 'error handling'))
        else:
            records=[json.loads(line) for line in (tmp_path/name).read_text().splitlines()]
            for record in records:
                record['bytes']=base64.b64encode(base64.b64decode(record['bytes']).replace(b'Filter',b'error handling')).decode()
            (tmp_path/name).write_text(''.join(json.dumps(r)+'\n' for r in records))
    assert covered_screens(tmp_path,SELECTION)=={1,2,3}


def test_dotted_mcp_name_fails_before_launch_instead_of_quoting_cli_key(tmp_path,monkeypatch):
    home=fresh(tmp_path/'home');monkeypatch.setenv('CODEX_HOME',str(home))
    (home/'config.toml').write_text('[mcp_servers."ambiguous.name"]\ncommand="extra"\n')
    with pytest.raises(ValueError,match='safely represented'):
        command(tmp_path,tmp_path/'state')


def test_real_neutral_graph_ready_and_missing_screen_fail_closed(tmp_path):
    import subprocess
    source=tmp_path/'neutral.html'; source.write_text(preflight.FIXTURE)
    graph=fresh(tmp_path/'graph')
    result=subprocess.run([sys.executable,'-c','from design_graph.interface.cli.build import main; main()',
                           str(source),'--db',str(graph/'original.db')], capture_output=True, text=True, timeout=60)
    assert result.returncode==0, result.stdout+result.stderr
    receipt=b_v4.graph_ready(graph,[dict(component='ObservatoryPage')])
    assert receipt['ready'] and receipt['screens'][0]['components']>0
    component=b_v4.graph_ready(graph,[dict(component='StarButton')])
    assert component['ready'] and component['screens'][0]['kind']=='component'
    assert component['screens'][0]['source_chars']>0
    with pytest.raises(ValueError,match='selected screen missing'):
        b_v4.graph_ready(graph,[dict(component='EntirelyAbsentPage')])
    with pytest.raises(ValueError,match='missing or empty'):
        b_v4.graph_ready(tmp_path/'missing',[])
