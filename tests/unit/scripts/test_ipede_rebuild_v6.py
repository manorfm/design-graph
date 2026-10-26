"""Neutral synthetic fixtures only. No measured reconstruction is executed."""
import base64
import json
import os
from pathlib import Path
import sys

import pytest

from scripts.ipede_rebuild_v6 import gates, protocol, runner
from scripts.ipede_rebuild_v6.audit import copy_scan, trace_gate
from scripts.ipede_rebuild_v6.common import write_json
from scripts.ipede_rebuild_v6.native_audit import covered_screens
from scripts.ipede_rebuild_v6.preflight import evidence


def rpc_fixture(root, *, relevant=True, completed=True, usage=True):
    """SYNTHETIC parser fixture, never real preflight evidence."""
    text='Neutral Observatory: function ObservatoryPage() { return <main style={{padding:24}}>Neutral Observatory</main>; }'
    name='get_full' if relevant else 'list_screens'
    result={'content':[{'type':'text','text':text}]}
    requests=[{'id':1,'method':'initialize'}, {'method':'notifications/initialized'},
              {'id':2,'method':'tools/list'}, {'id':3,'method':'tools/call','params':{'name':name,'arguments':{'name':'ObservatoryPage'}}}]
    responses=[{'id':1,'result':{'serverInfo':{'name':'synthetic'}}},
               {'id':2,'result':{'tools':[{'name':name}]}}, {'id':3,'result':result}]
    with (root/'transcript.jsonl').open('w') as f:
        for direction,values in [('client',requests),('server',responses)]:
            data=''.join(json.dumps(v)+'\n' for v in values).encode()
            # Split mid-message to test byte stream reassembly.
            for chunk in [data[:17],data[17:]]:
                f.write(json.dumps({'direction':direction,'bytes':base64.b64encode(chunk).decode()})+'\n')
    events=[{'type':'item.completed','item':{'id':'m1','type':'mcp_tool_call','server':'design-graph',
            'tool':name,'arguments':{'name':'ObservatoryPage'},'status':'completed','error':None,'result':result}}]
    if completed:
        event={'type':'turn.completed'}
        if usage:event['usage']={'input_tokens':100,'cached_input_tokens':80,'output_tokens':10}
        events.append(event)
    (root/'events.jsonl').write_text(''.join(json.dumps(v)+'\n' for v in events))
    write_json(root/'metrics.json',{'stop_reason':None,'exit_code':0})
    (root/'stderr.log').touch();(root/'server-stderr.log').touch()
    return events


def test_real_usage_parser_null_and_cache_subset():
    assert runner.final_usage([])==dict(input_tokens=None,cached_input_tokens=None,output_tokens=None)
    assert runner.final_usage([{'input_tokens':100,'cached_input_tokens':80,'output_tokens':9}])['input_tokens']==100
    with pytest.raises(ValueError):runner.final_usage([{'input_tokens':2,'cached_input_tokens':3}])
    with pytest.raises(ValueError):runner.final_usage([{'input_tokens':True}])


def test_rpc_native_crosscheck(tmp_path):
    rpc_fixture(tmp_path)
    assert evidence(tmp_path,required_text='Neutral Observatory',require_usage=True)
    assert covered_screens(tmp_path,[{'component':'ObservatoryPage'}])=={1}
    events=rpc_fixture(tmp_path);events[0]['item']['arguments']={'name':'unrelated'}
    (tmp_path/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
    with pytest.raises(ValueError):evidence(tmp_path,require_usage=True)
    assert covered_screens(tmp_path,[{'component':'ObservatoryPage'}])==set()


@pytest.mark.parametrize('kwargs',[{'relevant':False},{'completed':False},{'usage':False}])
def test_decorative_incomplete_or_missing_usage_rejected(tmp_path,kwargs):
    rpc_fixture(tmp_path,**kwargs)
    with pytest.raises(ValueError):evidence(tmp_path,required_text='Neutral Observatory',require_usage=True)


def test_zero_mcp_and_guard_refusal_rejected(tmp_path):
    rpc_fixture(tmp_path)
    (tmp_path/'transcript.jsonl').write_text('')
    with pytest.raises(ValueError):evidence(tmp_path)
    rpc_fixture(tmp_path);(tmp_path/'stderr.log').write_text('rejected by guard')
    with pytest.raises(ValueError,match='refusal'):evidence(tmp_path)


def test_freeze_approval_and_tampering(tmp_path):
    root=tmp_path/'private';root.mkdir();prep=root/'preparation';prep.mkdir();(prep/'input').write_text('neutral')
    instrument=tmp_path/'instrument';instrument.mkdir();(instrument/'run.py').write_text('neutral')
    sha=gates.freeze(root,instrument,{'model':'fixture'})
    with pytest.raises(ValueError,match='pending TL'):gates.approval(root,instrument,{'model':'fixture'})
    write_json(root/'TL-approval.json',{'approved':True,'reviewer_role':'TL','reviewer':'fixture','reviewed_at':'fixture','freeze_sha256':sha})
    gates.approval(root,instrument,{'model':'fixture'})
    with pytest.raises(ValueError):gates.approval(root,instrument,{'model':'changed'})
    (prep/'input').write_text('changed')
    with pytest.raises(ValueError,match='freeze changed'):gates.approval(root,instrument,{'model':'fixture'})


def test_prompt_access_and_order_symmetry(tmp_path,monkeypatch):
    assert protocol.prompt('A').removesuffix(protocol.CONDITIONS['A']) == protocol.prompt('B').removesuffix(protocol.CONDITIONS['B'])
    assert protocol.ORDER==[(1,'A'),(1,'B'),(2,'B'),(2,'A'),(3,'A'),(3,'B')]
    assert '/home/' not in protocol.COMMON
    monkeypatch.setattr(runner,'inherited_servers',lambda _:[])
    a=runner.command(tmp_path,tmp_path/'state')
    b=runner.command(tmp_path,tmp_path/'state',{'command':'python','pythonpath':'src','graph':'graph'})
    for cmd in [a,b]:
        assert 'workspace-write' in cmd and 'gpt-6.1-sol' in cmd
        assert 'model_reasoning_effort="medium"' in cmd
        assert not any('bypass' in x or 'ignore-rules' in x for x in cmd)
    with pytest.raises(ValueError):gates.disjoint(tmp_path,tmp_path/'oracle')
    with pytest.raises(ValueError):gates.socket_precheck('/'+'x'*120)
    assert gates.socket_precheck('/neutral-synthetic-path')['passed']


def fake_execute(tmp_path,script,**kwargs):
    work=tmp_path/'work';work.mkdir();(work/'output').mkdir();proof=tmp_path/'evidence';proof.mkdir()
    return runner.execute([sys.executable,'-c',script],work,proof,'neutral synthetic fixture',{},seconds=5,**kwargs)


def test_limit_really_stops_child(tmp_path):
    script="import json,time,pathlib;[print(json.dumps({'type':'item.started','item':{'id':str(i),'type':'command_execution'}}),flush=True) for i in range(2)];time.sleep(1);pathlib.Path('should-not-exist').touch();time.sleep(5)"
    result=fake_execute(tmp_path,script,limit=1)
    assert result['stop_reason']=='tool_limit'
    assert result['tool_calls']==2
    assert not (tmp_path/'work/should-not-exist').exists()
    assert json.loads((tmp_path/'evidence/process.json').read_text())['closed']


def test_mcp_after_write_cannot_open_gate(tmp_path):
    script="import pathlib,time;pathlib.Path('output/page.html').write_text('synthetic');time.sleep(2)"
    result=fake_execute(tmp_path,script,selections=[{'component':'ObservatoryPage'}])
    assert result['stop_reason']=='output_before_screen_queries'
    assert result['queried_screen_indexes']==[]


def test_refusal_stops_without_fallback(tmp_path):
    script="import time;print('rejected by guard',flush=True);time.sleep(4)"
    assert fake_execute(tmp_path,script)['stop_reason']=='guard_refusal'


def test_started_completed_count_once(tmp_path):
    script="import json;[print(json.dumps({'type':t,'item':{'id':'1','type':'command_execution'}}),flush=True) for t in ['item.started','item.completed']]"
    result=fake_execute(tmp_path,script,limit=10)
    assert result['tool_calls']==1 and result['operations_by_type']=={'command_execution':1}


def test_copy_and_access_gate(tmp_path):
    source=tmp_path/'neutral-source';output=tmp_path/'neutral-output'
    original='function Fixture(){'+''.join(f'const value{i} = "neutral{i}";' for i in range(40))+'}'
    source.write_text('<script>'+original+'</script>')
    output.write_text('<style>body{color:blue}</style><script>'+original+'</script>')
    with pytest.raises(ValueError,match='copied'):copy_scan(source,output)
    output.write_text('<style>body{color:green}</style><main>Independent neutral fixture</main>')
    assert copy_scan(source,output)['human_trace_review_required']
    with pytest.raises(ValueError):trace_gate([{'command':'cat ../oracle/file'}],'A')
    with pytest.raises(ValueError):trace_gate([{'item':{'type':'mcp_tool_call'}}],'A')


def test_public_schema_nulls_sanitization_manifest(tmp_path):
    import jsonschema
    folder=Path(protocol.__file__).parent
    data=json.loads((folder/'data.json').read_text());schema=json.loads((folder/'data.schema.json').read_text())
    jsonschema.validate(data,schema);gates.public_document(data)
    assert all(v is None for row in data['sessions'] for v in row['metrics'].values())
    for value in ['/home/example/private','file:///private','<script>secret','auth.json']:
        with pytest.raises(ValueError):gates.public_document({'leak':value})
    (tmp_path/'neutral').write_text('evidence');gates.manifest(tmp_path)
    assert 'neutral' in json.loads((tmp_path/'manifest.private.json').read_text())['files']


def test_missing_final_turn_cannot_pass_as_usage():
    with pytest.raises(ValueError):runner.completed_usage([{'type':'turn.failed'}])
    with pytest.raises(ValueError):runner.completed_usage([{'type':'item.completed','usage':{'input_tokens':1,'output_tokens':2}}])
    with pytest.raises(ValueError):runner.completed_usage([{'type':'turn.completed','usage':{'input_tokens':2}}])
    assert runner.completed_usage([{'type':'turn.completed','usage':{'input_tokens':2,'output_tokens':1}}])['cached_input_tokens'] is None


def test_public_uncollected_zero_is_invalid():
    import jsonschema
    folder=Path(protocol.__file__).parent
    data=json.loads((folder/'data.json').read_text());schema=json.loads((folder/'data.schema.json').read_text())
    data['sessions'][0]['metrics']['input_tokens']=0
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(data,schema)


def test_collect_checks_pending_approval_before_any_launch(tmp_path,monkeypatch):
    from scripts.ipede_rebuild_v6 import __main__ as cli
    monkeypatch.setattr(cli,'identity',lambda *a,**k:{'fixture':True})
    monkeypatch.setattr(cli,'approval',lambda *a:(_ for _ in ()).throw(ValueError('pending TL')))
    monkeypatch.setattr(runner,'execute',lambda *a,**k:pytest.fail('must not launch'))
    with pytest.raises(ValueError,match='pending TL'):cli.collect(tmp_path,tmp_path)
    assert not (tmp_path/'sessions').exists()


def test_private_manifest_detects_hashes_and_no_self_reference(tmp_path):
    (tmp_path/'evidence').mkdir();(tmp_path/'evidence/raw').write_bytes(b'neutral')
    first=gates.manifest(tmp_path)
    receipt=json.loads((tmp_path/'manifest.private.json').read_text())
    assert 'manifest.private.json' not in receipt['files']
    assert first==gates.manifest(tmp_path)


def test_mcp_input_mutation_before_query_is_also_stopped(tmp_path):
    script="import pathlib,time;pathlib.Path('temporary-implementation.js').write_text('fixture');time.sleep(2)"
    result=fake_execute(tmp_path,script,selections=[{'component':'ObservatoryPage'}])
    assert result['stop_reason']=='output_before_screen_queries'


def test_successful_target_query_precedes_output(tmp_path):
    proof=tmp_path/'evidence';proof.mkdir();events=rpc_fixture(proof)
    work=tmp_path/'work';work.mkdir();(work/'output').mkdir()
    script='import json,time,pathlib;print('+repr(json.dumps(events[0]))+',flush=True);time.sleep(.3);pathlib.Path("output/page.html").write_text("synthetic independent fixture")'
    result=runner.execute([sys.executable,'-c',script],work,proof,'synthetic fixture',{},seconds=5,limit=10,selections=[{'component':'ObservatoryPage'}])
    assert result['stop_reason'] is None
    assert result['queried_screen_indexes']==[1]
    assert (proof/'workspace-writes.jsonl').is_file()


def test_preflight_evidence_tamper_closes_gate(tmp_path,monkeypatch):
    from scripts.ipede_rebuild_v6 import preflight as pf
    from scripts.ipede_rebuild_v6.common import hashes
    folder=tmp_path/'preflight-v6';folder.mkdir();proof=folder/'evidence';proof.mkdir()
    rpc_fixture(proof)
    write_json(proof/'catalogue.json',[{'name':'get_full'}])
    monkeypatch.setattr(pf,'identity',lambda *a,**k:{'neutral':'identity'})
    (tmp_path/'freeze.json').write_text('synthetic freeze')
    write_json(folder/'gate.json',{'protocol':pf.protocol('v6'),'success':True,'freeze_sha256':gates.digest(tmp_path/'freeze.json'),
        'identity':{'neutral':'identity'},'evidence_hashes':hashes(proof)})
    pf.validate_gate(tmp_path,Path(sys.executable),tmp_path,version='v6')
    (proof/'events.jsonl').write_text('')
    with pytest.raises(ValueError,match='evidence changed'):pf.validate_gate(tmp_path,Path(sys.executable),tmp_path,version='v6')


def test_timeout_closes_only_owned_process(tmp_path):
    work=tmp_path/'work';work.mkdir();(work/'output').mkdir();proof=tmp_path/'evidence';proof.mkdir()
    result=runner.execute([sys.executable,'-c','import time;time.sleep(20)'],work,proof,'synthetic',{},seconds=.1,limit=10)
    assert result['stop_reason']=='timeout'
    assert json.loads((proof/'process.json').read_text())['closed']


@pytest.mark.parametrize('count,reason',[(119,None),(120,None),(121,'tool_limit')])
def test_explicit_120_boundary_and_failed_events(tmp_path,count,reason):
    # SYNTHETIC native events; one invocation ID even across started/completed.
    script='''import json
for i in range(COUNT):
 for t in ['item.started','item.completed','item.completed']:
  print(json.dumps({'type':t,'item':{'id':str(i),'type':'command_execution','exit_code':7 if i==0 else 0,'status':'completed'}}),flush=True)
'''.replace('COUNT',str(count))
    result=fake_execute(tmp_path,script)
    assert result['tool_calls']==count
    assert result['stop_reason']==reason
    assert len(result['errors'])==1 and result['errors'][0]['exit_code']==7
    assert result['operations_by_type']=={'command_execution':count}


def test_subcommands_diagnostic_not_operations(tmp_path):
    item={'id':'command-1','type':'command_execution','command':'echo neutral; echo fixture','subcommands':[{'id':'s1'},{'id':'s2'}]}
    result=fake_execute(tmp_path,'import json;print('+repr(json.dumps({'type':'item.completed','item':item}))+')')
    assert result['tool_calls']==1


@pytest.mark.parametrize('command',[
 'python -m http.server 8111','node -e "require(\'http\').createServer().listen(8)"',
 'playwright screenshot neutral.html x.png','chromium --headless neutral.html',
 'npx vite','esbuild input.js --outfile=out.js','babel input.js',
 'cat ../sibling/source','cat /private/oracle/state.json','cat /home/neutral/sibling/source',
 'python -c "import socket; socket.socket().bind((\'localhost\',8123))"'])
def test_neutral_generation_trace_rejections(command):
    with pytest.raises(ValueError):trace_gate([{'item':{'type':'command_execution','command':command}}],'B',Path('/neutral/work'))


def test_trace_allows_source_mention_and_search():
    events=[{'item':{'id':'r','type':'command_execution','command':'rg -n Heading input/original.html','aggregated_output':'React browser source'}}]
    assert trace_gate(events,'A')['read_isolation'] is False


def test_real_cli_collect_routing_pending_and_tampered_freeze(tmp_path,monkeypatch):
    from scripts.ipede_rebuild_v6 import __main__ as cli
    import subprocess
    instrument=Path(cli.__file__).parent
    (tmp_path/'preparation').mkdir();(tmp_path/'preparation/neutral').write_text('fixture')
    monkeypatch.setattr(cli,'identity',lambda *a,**k:{'fixture':True})
    gates.freeze(tmp_path,instrument,{'fixture':True})
    monkeypatch.setattr(sys,'argv',['ipede','collect','--root',str(tmp_path)])
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:pytest.fail('Popen must never happen'))
    with pytest.raises(ValueError,match='pending TL'):cli.main()
    (tmp_path/'preparation/neutral').write_text('tampered fixture')
    with pytest.raises(ValueError,match='freeze changed'):cli.main()
    assert not (tmp_path/'sessions').exists()


def test_preflight_requires_frozen_identity_before_popen(tmp_path,monkeypatch):
    from scripts.ipede_rebuild_v6 import preflight as pf
    import subprocess
    monkeypatch.setattr(pf,'identity',lambda *a,**k:{'fixture':True})
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:pytest.fail('must not launch'))
    with pytest.raises(FileNotFoundError):pf.preflight(tmp_path,Path(sys.executable),tmp_path)
    assert not (tmp_path/'preflight-v6').exists()


def synthetic_rubric():
    """Neutral assertions, public denominators only, no proprietary oracle."""
    from scripts.ipede_rebuild_v6.rubric import THRESHOLDS,CRITICAL
    pub=json.loads(Path(protocol.__file__).with_name('rubric.public.json').read_text())
    rows=[]
    for den in pub['denominators']:
        checks={}
        for kind in ['visual','functional','usability']:
            checks[kind]=[{'id':f"{den['page']}:{den['viewport']}:{kind}:{i}",
                'reference':{'dom':'neutral.json','image':'neutral.png','dom_sha256':'0'*64,'image_sha256':'1'*64},
                'rule':'Neutral explicit assertion','action':None,'assert':{'text':'Neutral Observatory','controls':[]}} for i in range(den[kind])]
        rows.append({'page':den['page'],'viewport':den['viewport'],'group':'neutral','key':'neutral','entry':[],'checks':checks})
    return {'version':1,'thresholds':THRESHOLDS,'critical_failures':CRITICAL,'rows':rows,'original_negatives':['Neutral fixture only'],'scoring':'Fixed assertions'}


def usability_reviews(evaluation, rubric, page, evidence=None):
    from scripts.ipede_rebuild_v6.rubric import negative_hash
    for row in evaluation['rows']:
        row['usability_review']={c['id']:{'negative_sha256':negative_hash(c),
            'exact_inherited':False,'no_regression':True,'explanation':'Neutral human review of exact state, controls and clipping',
            'evidence':evidence or {'path':'neutral.png','sha256':'a'*64}}
            for r in rubric['rows'] if r['page']==page and r['viewport']==row['viewport'] for c in r['checks']['usability']}
    return evaluation


def test_results_missing_delta_quality_and_schema(tmp_path):
    from scripts.ipede_rebuild_v6 import results
    from scripts.ipede_rebuild_v6.rubric import validate
    rubric=synthetic_rubric();validate(rubric)
    prep=tmp_path/'preparation';prep.mkdir();write_json(prep/'rubric.private.json',rubric)
    data=results.materialize(tmp_path,tmp_path/'public')
    assert data['status']=='not_collected'
    assert all(v is None for s in data['sessions'] for v in s['metrics'].values())
    assert results.delta(0,10)=={'absolute':10,'percent':None}
    assert results.delta(None,1)=={'absolute':None,'percent':None}
    assert results.delta(20,10)=={'absolute':-10,'percent':-50}
    assert results.delta(20,None)=={'absolute':None,'percent':None}
    assert all(r['conclusion']=='inconclusivo' for r in data['comparisons'])
    data['sessions'][0]['quality'][0]['functional']['denominator']+=1
    import jsonschema
    with pytest.raises(jsonschema.ValidationError):results.validate_data(data)


def test_evaluation_schema_unknown_denominators_and_critical_failures():
    from scripts.ipede_rebuild_v6 import results
    rubric=synthetic_rubric()
    e={'freeze_sha256':'0'*64,'rubric_sha256':'1'*64,'output_sha256':'2'*64,'events_sha256':'3'*64,'metrics_sha256':'4'*64,'reviewer':'neutral human','reviewed_at':'neutral test',
       'trace_review':True,'access_review':True,'independence_review':True,'evaluation_seconds':1,
       'rows':[{'viewport':vp,'checks':{c['id']:True for r in rubric['rows'] if r['page']==1 and r['viewport']==vp for checks in r['checks'].values() for c in checks},'critical_failures':[]} for vp in ['1280x900','390x844']]}
    usability_reviews(e,rubric,1)
    q=results.evaluate(rubric,1,e)
    assert results.accepted(q,e,rubric) is True
    e['rows'][0]['critical_failures']=['unusable_primary_action']
    assert results.accepted(results.evaluate(rubric,1,e),e,rubric) is False
    e['rows'][0]['critical_failures']=[]
    key=next(iter(e['rows'][0]['checks']));e['rows'][0]['checks'][key]=None
    assert results.accepted(results.evaluate(rubric,1,e),e,rubric) is None
    del e['rows'][0]['checks'][key]
    import jsonschema
    with pytest.raises(jsonschema.ValidationError):results.evaluate(rubric,1,e)


def test_effectiveness_dominance_and_missing():
    from copy import deepcopy
    from scripts.ipede_rebuild_v6 import results
    a={'metrics':{**dict.fromkeys(results.RESOURCE,100),'accepted':True,'valid':True},'quality':[dict.fromkeys(results.KINDS,{'score':.9}) for _ in range(2)]}
    b=deepcopy(a)
    for k in results.RESOURCE:b['metrics'][k]=80
    assert results.conclusion(a,b)=='economizou mantendo qualidade'
    b['quality'][0]['visual']={'score':.8}
    assert results.conclusion(a,b)=='inconclusivo'
    b=deepcopy(a);b['metrics']['operations']=120
    assert results.conclusion(a,b)=='não trouxe ganho'
    b['quality'][0]['visual']={'score':1.}
    assert results.conclusion(a,b)=='melhorou qualidade com custo adicional'
    b['metrics']['input_tokens']=None
    assert results.conclusion(a,b)=='inconclusivo'
    b=deepcopy(a);b['metrics']['accepted']=False;b['metrics']['input_tokens']=1
    assert results.conclusion(a,b)=='inconclusivo'


def test_six_real_format_sessions_materialize_neutral_metrics(tmp_path,monkeypatch):
    from scripts.ipede_rebuild_v6 import results
    from scripts.ipede_rebuild_v6 import preflight as pf
    from scripts.ipede_rebuild_v6.common import digest
    rubric=synthetic_rubric();prep=tmp_path/'preparation';prep.mkdir()
    write_json(prep/'rubric.private.json',rubric);write_json(prep/'setup.private.json',{'index_seconds':4})
    write_json(tmp_path/'freeze.json',{'identity':{'sha256':'a'*64},'files':{'rubric.private.json':digest(prep/'rubric.private.json')}})
    monkeypatch.setattr(pf,'evidence',lambda *a,**k:[])
    for page,lane in protocol.ORDER:
        base=tmp_path/f'sessions/{page}-{lane}';proof=base/'evidence';proof.mkdir(parents=True)
        work=base/'work';(work/'input').mkdir(parents=True);(work/'output').mkdir()
        (work/'input/original.html').write_text('<main>Neutral source</main>')
        (work/'output/page.html').write_text('<style>main{color:blue}</style><main>Neutral result</main>')
        (proof/'events.jsonl').write_text(json.dumps({'type':'turn.completed','usage':{'input_tokens':100 if lane=='A' else 80,'output_tokens':10}})+'\n')
        (proof/'transcript.jsonl').touch()
        # SYNTHETIC metrics in the exact runner format, not benchmark evidence.
        write_json(proof/'metrics.json',{'usage':{'input_tokens':100 if lane=='A' else 80,'cached_input_tokens':None,'output_tokens':10},'seconds':2,'supervision_seconds':.1,'tool_calls':2,'operations_by_type':{'command_execution':2},'errors':[],'stop_reason':None,'exit_code':0,'queried_screen_indexes':[1]})
        e={k:digest(path) for k,path in {'freeze_sha256':tmp_path/'freeze.json','rubric_sha256':prep/'rubric.private.json','output_sha256':work/'output/page.html','events_sha256':proof/'events.jsonl','metrics_sha256':proof/'metrics.json'}.items()}
        e.update({'reviewer':'neutral test human','reviewed_at':'neutral synthetic','trace_review':True,'access_review':True,'independence_review':True,'evaluation_seconds':3,
                  'rows':[{'viewport':vp,'checks':{c['id']:True for r in rubric['rows'] if r['page']==page and r['viewport']==vp for cs in r['checks'].values() for c in cs},'critical_failures':[]} for vp in ['1280x900','390x844']]})
        (proof/'neutral.png').write_bytes(b'neutral evidence')
        usability_reviews(e,rubric,page,{'path':'neutral.png','sha256':digest(proof/'neutral.png')})
        write_json(proof/'evaluation.private.json',e)
    data=results.materialize(tmp_path,tmp_path/'result')
    assert data['status']=='collected'
    assert data['totals']['input_tokens']==540  # no cache addition
    assert data['totals']['cached_input_tokens'] is None
    assert data['total_generation_with_setup_seconds']==16
    assert data['lane_totals']['A']['generation_seconds']==6
    assert data['lane_totals']['B']['generation_seconds']==6
    assert data['setup_comparison']=={'A_generation_seconds':6,'B_generation_plus_setup_seconds':10,'delta':{'absolute':4,'percent':100*4/6}}
    assert data['comparisons'][0]['deltas']['input_tokens']=={'absolute':-20,'percent':-20}
    assert all(r['conclusion']=='inconclusivo' for r in data['comparisons'])  # missing real cache => no effectiveness claim
    assert all(s['metrics']['accepted'] is True for s in data['sessions'])
    assert all(s['metrics']['money'] is None for s in data['sessions'])
    proof=tmp_path/'sessions/1-A/evidence'
    (proof/'neutral.png').write_bytes(b'tampered evidence')
    with pytest.raises(ValueError,match='usability review evidence'):results.materialize(tmp_path,tmp_path/'bad-evidence')
    assert not (tmp_path/'bad-evidence').exists()
    (proof/'neutral.png').write_bytes(b'neutral evidence')
    (tmp_path/'sessions/1-A/work/output/page.html').write_text('changed neutral output')
    with pytest.raises(ValueError,match='binding changed'):results.materialize(tmp_path,tmp_path/'should-not-exist')
    assert not (tmp_path/'should-not-exist').exists()


def test_private_rubric_rejects_missing_assert_and_changed_threshold():
    import jsonschema
    from scripts.ipede_rebuild_v6.rubric import validate
    r=synthetic_rubric();del r['rows'][0]['checks']['functional'][0]['assert']
    with pytest.raises(jsonschema.ValidationError):validate(r)
    r=synthetic_rubric();r['thresholds']={**r['thresholds'],'functional':.5}
    with pytest.raises(jsonschema.ValidationError):validate(r)


def test_exact_inherited_clipping_separate_from_absolute_and_new_regressions():
    from copy import deepcopy
    import jsonschema
    from scripts.ipede_rebuild_v6 import results
    from scripts.ipede_rebuild_v6.rubric import validate
    r=synthetic_rubric()
    check=next(row for row in r['rows'] if row['page']==3 and row['viewport']=='390x844')['checks']['usability'][0]
    check['inherited_negative']={'reference':deepcopy(check['reference']),
        'description':'Neutral original: exact label clipped at right edge in initial state only',
        'reviewer':'neutral preparatory reviewer','reviewed_at':'2026-10-26'}
    validate(r)
    e={**{k:'a'*64 for k in ['freeze_sha256','rubric_sha256','output_sha256','events_sha256','metrics_sha256']},
       'reviewer':'neutral downstream human','reviewed_at':'2026-10-26','trace_review':True,'access_review':True,
       'independence_review':True,'evaluation_seconds':1,
       'rows':[{'viewport':vp,'critical_failures':[],'checks':{c['id']:True for row in r['rows'] if row['page']==3 and row['viewport']==vp for cs in row['checks'].values() for c in cs}} for vp in ['1280x900','390x844']]}
    usability_reviews(e,r,3)
    mobile=e['rows'][1];key=check['id'];mobile['checks'][key]=False
    # Without exact human attestation even the known original defect fails.
    assert results.accepted(results.evaluate(r,3,e),e,r) is False
    mobile['usability_review'][key]['exact_inherited']=True
    q=results.evaluate(r,3,e)
    assert results.accepted(q,e,r) is True
    assert q[1]['usability']['score']<1 and q[1]['reference_usability']['score']==1
    assert q[1]['usability_negatives'][0]['inherited'] is True
    a={'metrics':{**dict.fromkeys(results.RESOURCE,100),'accepted':True,'valid':True},'quality':q}
    b=deepcopy(a);b['metrics']['operations']=90
    assert results.conclusion(a,b)=='economizou mantendo qualidade'  # faithful clipping remains comparable
    b['metrics']['operations']=100
    assert results.conclusion(a,b)=='não trouxe ganho'
    b['quality'][1]['usability']['score']=1
    assert results.conclusion(a,b)=='melhorou qualidade sem custo adicional'
    assert b['quality'][1]['visual']==a['quality'][1]['visual']  # no fidelity credit for usability gain
    b['quality'][1]['visual']['score']=.9
    assert results.conclusion(a,b)=='inconclusivo'
    assert len(results.original_negatives(r))==1
    # New inaccessible control, even inside the same check/state, rejects.
    mobile['usability_review'][key]['no_regression']=False
    assert results.accepted(results.evaluate(r,3,e),e,r) is False
    desktop_key=next(iter(e['rows'][0]['checks']));e['rows'][0]['checks'][desktop_key]=None
    assert results.accepted(results.evaluate(r,3,e),e,r) is False  # known regression wins over missing data
    e['rows'][0]['checks'][desktop_key]=True
    mobile['usability_review'][key]['no_regression']=True
    another=next(k for k in mobile['usability_review'] if k!=key);mobile['checks'][another]=False
    assert results.accepted(results.evaluate(r,3,e),e,r) is False
    mobile['usability_review'][another]['exact_inherited']=True
    with pytest.raises(jsonschema.ValidationError):results.evaluate(r,3,e)
    mobile['usability_review'][another]['exact_inherited']=False;mobile['checks'][another]=True
    mobile['checks'][key]=None
    assert results.accepted(results.evaluate(r,3,e),e,r) is None
    mobile['checks'][key]=False
    mobile['usability_review'][key]['negative_sha256']='f'*64
    with pytest.raises(jsonschema.ValidationError):results.evaluate(r,3,e)
    usability_reviews(e,r,3);del mobile['usability_review'][key]
    with pytest.raises(jsonschema.ValidationError):results.evaluate(r,3,e)
    # Reference substitution cannot broaden a frozen negative.
    check['inherited_negative']['reference']['image_sha256']='b'*64
    with pytest.raises(ValueError,match='exact check'):validate(r)


@pytest.mark.parametrize('dimension',['visual','functional','usability'])
def test_quality_gain_equal_physical_resources(dimension):
    from copy import deepcopy
    from scripts.ipede_rebuild_v6 import results
    a={'metrics':{**dict.fromkeys(results.RESOURCE,100),'accepted':True,'valid':True,'money':None},
       'quality':[{k:{'score':.9} for k in results.KINDS} for _ in range(2)]}
    b=deepcopy(a);b['quality'][0][dimension]['score']=1
    assert results.conclusion(a,b)=='melhorou qualidade sem custo adicional'
    # Cache is a subset; more cache does not change resource equality.
    b['metrics']['cached_input_tokens']=80
    assert results.conclusion(a,b)=='melhorou qualidade sem custo adicional'
    b['metrics']['operations']=99
    assert results.conclusion(a,b)=='economizou mantendo qualidade'
    b['metrics']['input_tokens']=101
    assert results.conclusion(a,b)=='inconclusivo'  # mixed resource directions
    b['metrics']['operations']=100
    assert results.conclusion(a,b)=='melhorou qualidade com custo adicional'
    b['quality'][1]['visual']['score']=.8
    assert results.conclusion(a,b)=='inconclusivo'  # no quality trade forgiveness
    b=deepcopy(a)
    assert results.conclusion(a,b)=='não trouxe ganho'
    b['quality'][0][dimension]['score']=1;b['metrics']['cached_input_tokens']=None
    assert results.conclusion(a,b)=='inconclusivo'
