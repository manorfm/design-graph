"""Synthetic fixtures only. Never reads a private prototype or starts Codex."""
import base64
import json
import os
from pathlib import Path
import sys

import pytest

from scripts.ipede_threepages.common import digest, environment, fresh, hashes, verify, write_json
from scripts.ipede_threepages.inventory import byte_offset, decode, route_inventory
from scripts.ipede_threepages.runner import command, execute, index_command, run
from scripts.ipede_threepages.report import report


def module(text, offset=0):
    return dict(file='synthetic.js',text=text,offset=offset,id='synthetic')


def router():
    return '''const NAV = [
{ key: 'one', label: 'One' },
{ key: 'two', label: 'Two' },
{ key: 'three', label: 'Three' },
{ key: 'four', label: 'Four' },
];
// function App() { documentation must not be parsed
// const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{invalid}/*EDITMODE-END*/;
const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{"plan":"default"}/*EDITMODE-END*/;
function NotAPageHelper() { return null; }
function FirstPage() { const [q, setQ] = useState(''); return null; }
function SecondPage() { return null; }
function ThirdPage() { return null; }
function PlaceholderPage() { return null; }
window.Views.Alias = SecondPage;
function App() {
return <main>{page === 'one' ? (<FirstPage/>) : page === 'two' ? (<window.Views.Alias/>) : page === 'three' ? (<ThirdPage/>) : (<PlaceholderPage/>)}</main>;
}
'''


def test_inventory_only_actual_routes_aliases_bytes_and_lower_median():
    source='// café\n'+router()
    result=route_inventory([module(source,10)])
    assert [r['component'] for r in result['routes']]==['FirstPage','SecondPage','ThirdPage','PlaceholderPage']
    assert [r['key'] for r in result['selection']]==['one','two','three']
    assert result['selection_indexes']==[0,1,2]
    assert result['routes'][-1]['exclusion_reason']
    assert len(result['eligible_routes'])==3
    first=result['routes'][0]
    assert first['application_offset_bytes']==10+len(source[:source.index('function FirstPage')].encode())
    assert first['entry']['tweaks']=={'plan':'default'}
    assert not result['review_required']
    assert byte_offset('éa',1)==2


def test_unknown_router_fails_closed():
    with pytest.raises(ValueError,match='unsupported router'):route_inventory([module('function HelperPage() {}')])


def test_decode_preserves_vendor_but_excludes_from_application(tmp_path):
    manifest={
        'vendor':{'mime':'text/javascript','data':base64.b64encode(b'/** @license React\n * react.production.min.js */').decode()},
        'app':{'mime':'text/javascript','data':base64.b64encode(router().encode()).decode()},
        'asset':{'mime':'image/png','data':base64.b64encode(b'fake asset').decode()}}
    source=tmp_path/'fixture.html'
    source.write_text('<script type="__bundler/manifest">'+json.dumps(manifest)+'</script><script type="__bundler/template">'+json.dumps('<html><script>const inline=1;</script></html>').replace('</', '<\\/')+'</script>')
    _,resources,modules=decode(source,tmp_path/'decoded')
    assert [r['application'] for r in resources]==[False,True,False]
    assert len(modules)==2 and modules[0]['offset']==0
    assert modules[1]['offset']==len(router().encode())+1
    assert len(list((tmp_path/'decoded').glob('resource-*')))==3


def test_freeze_detects_mutation(tmp_path):
    (tmp_path/'source').write_text('private synthetic')
    write_json(tmp_path/'freeze.json',{'files':hashes(tmp_path)})
    verify(tmp_path)
    (tmp_path/'source').write_text('changed')
    with pytest.raises(ValueError,match='frozen file changed'):verify(tmp_path)


def test_real_mcp_config_and_absence_are_different_only_in_config(tmp_path):
    a=command(tmp_path,tmp_path/'state')
    b=command(tmp_path,tmp_path/'state',dict(command='/existing/bin/design-mcp',pythonpath='/worktree/src',graph='/private/graph'))
    assert 'mcp_servers={}' in a
    assert 'mcp_servers={}' not in b
    assert 'mcp_servers.design-graph.command="/existing/bin/design-mcp"' in b
    assert '--sandbox' in a and 'workspace-write' in b
    assert not any('bypass' in arg or arg.startswith('--ignore-') for arg in a+b)
    assert a[a.index('-m')+1]=='gpt-6.1-sol'
    assert 'model_reasoning_effort="medium"' in b
    assert not any('query_service' in arg for arg in b)


def test_run_requires_exact_parent_approval_before_creating_runs(tmp_path):
    prep=fresh(tmp_path/'preparation');write_json(prep/'freeze.json',{'files':{}})
    approval=tmp_path/'approval.json';write_json(approval,{'approved':True,'freeze_sha256':'wrong'})
    with pytest.raises(ValueError,match='parent approval'):run(tmp_path,approval)
    assert not (tmp_path/'runs').exists()


def fake_script(tmp_path, body):
    script=tmp_path/'fake.py';script.write_text(body)
    work=fresh(tmp_path/'work');(work/'output').mkdir()
    evidence=fresh(tmp_path/'evidence')
    return script,work,evidence


def test_observer_raw_mcp_usage_and_artifact_timing(tmp_path):
    script,work,evidence=fake_script(tmp_path,'''import json,time
from pathlib import Path
Path('output/page-1.html').write_text('one')
print(json.dumps({'type':'item.completed','item':{'id':'m1','type':'mcp_tool_call','server':'design-graph','result':{'private':'retained'}}}),flush=True)
time.sleep(.15)
Path('output/page-1.html').write_text('two')
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':123,'output_tokens':4}}),flush=True)
time.sleep(.15)
''')
    result=execute([sys.executable,str(script)],work,evidence,'',os.environ.copy(),seconds=3)
    assert result['tool_calls']==1
    assert result['raw_usage']==[{'input_tokens':123,'output_tokens':4}]
    obs=result['output_artifact_observations']['page-1.html']
    assert obs['last_observed_seconds']>obs['first_observed_seconds']
    assert result['accepted_timing'] is None
    assert 'retained' in (evidence/'events.jsonl').read_text()
    assert 'received_monotonic' in (evidence/'observed-events.jsonl').read_text()
    assert json.loads((evidence/'process.json').read_text())['closed']


def test_timeout_kills_process_group_including_inherited_pipe(tmp_path):
    script,work,evidence=fake_script(tmp_path,'''import subprocess,sys,time,signal
signal.signal(signal.SIGTERM,signal.SIG_IGN)
subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
time.sleep(30)
''')
    result=execute([sys.executable,str(script)],work,evidence,'',os.environ.copy(),seconds=.2)
    assert result['stop_reason']=='timeout'
    assert result['seconds']<5
    assert json.loads((evidence/'process.json').read_text())['closed']


def test_tool_limit_retains_failure_and_does_not_rerun(tmp_path):
    script,work,evidence=fake_script(tmp_path,'''import json,time
for i in range(10):
 print(json.dumps({'type':'item.completed','item':{'id':str(i),'type':'command_execution'}}),flush=True)
 time.sleep(.1)
''')
    result=execute([sys.executable,str(script)],work,evidence,'',os.environ.copy(),seconds=3,limit=2)
    assert result['stop_reason']=='tool_limit' and result['tool_calls']==2


def test_report_allowlist_excludes_client_copy_traces_and_paths(tmp_path):
    write_json(tmp_path/'run-results.private.json',{'A':{'seconds':1,'private_source':'DO NOT EXPORT','raw_usage':[{'input_tokens':4}]},'B':{'seconds':2}})
    write_json(tmp_path/'evaluation-results.private.json',[{'lane':'A','page':1,'viewport':'1280x900','private_dom':'DO NOT EXPORT','accepted':None}])
    out=report(tmp_path);text=(out/'data.json').read_text()
    assert 'DO NOT EXPORT' not in text and 'private_dom' not in text
    data=json.loads(text)
    assert data['contract']=='benchmark-ipede-v2' and data['round']=='iPede-3pages-v3'
    assert data['samples_per_condition']==1
    with pytest.raises(FileExistsError):report(tmp_path)


def test_scratch_alias_stays_physically_inside_root(tmp_path):
    env=environment(tmp_path)
    assert Path(env['TMPDIR']).resolve()==tmp_path/'tmp'
    assert env['CODEX_HOME']==os.environ['CODEX_HOME'] if 'CODEX_HOME' in os.environ else 'CODEX_HOME' not in env


def test_index_argv_is_accepted_by_real_cli_parser(tmp_path):
    from design_graph.interface.cli.build import parse_build_args
    argv=index_command(tmp_path/'bin',tmp_path/'source.html',tmp_path/'graph-B')
    parsed=parse_build_args(argv[1:])
    assert parsed.html_path==tmp_path/'source.html'
    assert parsed.db_path==tmp_path/'graph-B'/'original.db'


def test_real_mcp_config_is_valid_toml(tmp_path):
    import tomllib
    argv=command(tmp_path,tmp_path,dict(command='/bin/design-mcp',pythonpath='/work/src',graph='/private/graph-B'))
    config=tomllib.loads('\n'.join(argv[i+1] for i,arg in enumerate(argv) if arg=='-c'))
    server=config['mcp_servers']['design-graph']
    assert server['command']=='/bin/design-mcp'
    assert server['env']=={'PYTHONPATH':'/work/src','GRAPH_DIR':'/private/graph-B'}


def test_exit_samples_final_output_and_unterminated_raw_events(tmp_path):
    script,work,evidence=fake_script(tmp_path,'''import json
from pathlib import Path
Path('output/page-3.html').write_text('final')
print(json.dumps({'type':'item.started','item':{'id':'m','type':'mcp_tool_call'}}),flush=True)
print(json.dumps({'type':'item.completed','item':{'id':'m','type':'mcp_tool_call'}}),flush=True)
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':9,'output_tokens':2}}),end='',flush=True)
''')
    result=execute([sys.executable,str(script)],work,evidence,'',os.environ.copy(),seconds=3)
    assert result['raw_usage']==[{'input_tokens':9,'output_tokens':2}]
    assert result['tool_calls']==1
    assert result['output_artifact_observations']['page-3.html']['sha256']==digest(work/'output/page-3.html')
    assert result['raw_mcp_item_events']=={'item.started':1,'item.completed':1}
    assert len((evidence/'observed-events.jsonl').read_text().splitlines())==3


def test_even_implemented_route_count_uses_lower_median_and_retains_exclusions():
    source=router().replace("{ key: 'four', label: 'Four' },", "{ key: 'four', label: 'Four' },\n{ key: 'five', label: 'Five' },")
    source=source.replace('function PlaceholderPage()', 'function FourthPage() { return null; }\nfunction PlaceholderPage()')
    source=source.replace(': (<PlaceholderPage/>)', ": page === 'four' ? (<FourthPage/>) : (<PlaceholderPage/>)")
    result=route_inventory([module(source)])
    assert len(result['routes'])==5 and len(result['eligible_routes'])==4
    assert result['selection_indexes']==[0,1,3]
    assert [r['component'] for r in result['selection']]==['FirstPage','SecondPage','FourthPage']
    assert result['routes'][-1]['eligible'] is False
