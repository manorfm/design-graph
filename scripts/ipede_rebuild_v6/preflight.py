"""Neutral native MCP preflight, adapted from historical generic evidence checks."""
from __future__ import annotations
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from .common import digest, environment, fresh, hashes, write_json
from .runner import TIME_LIMIT, TOOL_LIMIT, cleanup, command, execute, guard_refusal, index_command, proxy, config_files

PROTOCOL = 'ipede-rebuild-v6-r2-preflight'


def protocol(version):
    if version not in {'v6', 'v6-r2'}:
        raise ValueError('unsupported preflight version')
    return PROTOCOL

FIXTURE = '''<!doctype html><html><body><script>
function StarButton() {
  return (<button style={{padding: '8px'}}>Inspect stars</button>);
}
function ObservatoryPage() {
  return (<main style={{backgroundColor: '#101820', padding: '24px'}}>
    <h1>Neutral Observatory</h1><StarButton />
  </main>);
}
</script></body></html>\n'''


def identity(python, worktree, root, *, version='v6-r2'):
    executor = shutil.which('codex')
    if not executor:
        raise ValueError('codex executor unavailable; policies must not be relaxed')
    home = Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex')))
    launcher = Path(executor).resolve()
    binaries = sorted((launcher.parent.parent/'node_modules/@openai').glob('codex-*/vendor/*/bin/codex'))
    binaries += sorted((launcher.parent.parent/'vendor').glob('*/bin/codex'))
    if launcher.read_bytes()[:2] == b'#!' and len(binaries) != 1:
        raise ValueError('cannot identify unique real executor binary')
    real_binary = binaries[0] if binaries else launcher
    files = [worktree/'scripts/validate_ipede_tmp_v1.py', worktree/'scripts/seal_ipede_tmp_v1.py', worktree/'tests/unit/scripts/test_ipede_tmp_v1.py', worktree/'docs/experiments/ipede-rebuild-v6-r2-tmp-v1.freeze.schema.json', worktree/'scripts/freeze_ipede_r2.py', worktree/'docs/experiments/ipede-rebuild-v6-r2.freeze.schema.json', worktree/'scripts/prepare_ipede_r2.py', worktree/'tests/unit/scripts/test_ipede_rebuild_v6.py', worktree/'pyproject.toml', worktree/'Makefile', real_binary, Path(shutil.which('node') or executor), *config_files(root), Path(executor), Path(python), python.parent/'design-mcp', python.parent/'design-graph', home/'config.toml']
    runtime_file=root/'preparation/runtime.private.json'
    runtime_inventory=json.loads(runtime_file.read_text()) if runtime_file.is_file() else None
    if runtime_inventory:
        from .lifecycle import validate
        validate(root)
        for path in runtime_inventory['workspaces'].values(): files += config_files(Path(path))
    # Bind inherited local policies/configuration without retaining their contents or auth.
    for parent in [worktree, *worktree.parents, root, *root.parents]:
        files += [parent/'AGENTS.md', parent/'AGENTS.override.md', parent/'.codex/config.toml']
    files += [home/'AGENTS.md', home/'AGENTS.override.md']
    files += sorted((home/'rules').glob('*.rules'))
    files += sorted((worktree/'.codex/rules').glob('*.rules'))
    import importlib.metadata, platform
    packages = {d.metadata['Name']:d.version for d in importlib.metadata.distributions()}
    payload = dict(runtime_inventory=runtime_inventory, packages=packages, python_version=platform.python_version(), protocol=protocol(version), executor=str(launcher), real_binary=str(real_binary), python=str(python),
                   worktree=str(worktree), custody_root=str(root), codex_home=str(home), seconds=TIME_LIMIT, limit=TOOL_LIMIT,
                   command=command(root/'<work>', Path('<state>'), proxy(python, worktree, Path('<graph>'), Path('<evidence>'))),
                   environment={k:os.environ.get(k) for k in ['PATH','CODEX_HOME','LANG','TZ']},
                   session_environment=environment_template(),
                   files={str(p): digest(p) if p.is_file() else None for p in files},
                   instrument={k:v for k,v in hashes(Path(__file__).parent).items() if '__pycache__' not in k and not k.endswith('.pyc')},
                   product={k:v for k,v in hashes(worktree/'src').items() if '__pycache__' not in k and not k.endswith('.pyc')})
    return dict(payload=payload, sha256=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest())


def evidence(folder, required_text=None, *, require_usage=False):
    """Require actual bidirectional RPC plus a matching successful native event."""
    metrics = json.loads((folder/'metrics.json').read_text())
    if metrics['stop_reason'] is not None or metrics['exit_code'] != 0:
        raise ValueError('preflight executor failed, refused or timed out')
    if guard_refusal((folder/'stderr.log').read_text() + (folder/'server-stderr.log').read_text()):
        raise ValueError('preflight guard refusal')
    streams = {'client': b'', 'server': b''}
    for line in (folder/'transcript.jsonl').read_text().splitlines():
        record = json.loads(line)
        streams[record['direction']] += base64.b64decode(record['bytes'], validate=True)
    requests = [json.loads(line) for line in streams['client'].splitlines() if line.strip()]
    responses = [json.loads(line) for line in streams['server'].splitlines() if line.strip()]
    def response(request):
        found = [r for r in responses if r.get('id') == request['id'] and 'result' in r and 'error' not in r]
        if len(found) != 1:
            raise ValueError('missing or ambiguous RPC response')
        return found[0]['result']
    init = [r for r in requests if r.get('method') == 'initialize']
    lists = [r for r in requests if r.get('method') == 'tools/list']
    if not init or not lists or not response(init[0]).get('serverInfo'):
        raise ValueError('missing initialize/tools/list handshake')
    if not any(r.get('method') == 'notifications/initialized' for r in requests):
        raise ValueError('missing initialized notification')
    catalogue = []
    for request in lists:
        result = response(request)
        catalogue.extend(result['tools'])
        cursor = result.get('nextCursor')
        if cursor and not any(r.get('params', {}).get('cursor') == cursor for r in lists):
            raise ValueError('incomplete catalogue pagination')
    names = {tool['name'] for tool in catalogue}
    events = [json.loads(line) for line in (folder/'events.jsonl').read_text().splitlines() if line.strip()]
    if any(e.get('type') in {'turn.failed', 'error'} for e in events):
        raise ValueError('native executor reported failure')
    if not any(e.get('type') == 'turn.completed' for e in events):
        raise ValueError('missing completed native turn')
    if require_usage:
        from .runner import completed_usage
        completed_usage(events)
    native = [e['item'] for e in events if e.get('type') == 'item.completed'
              and e.get('item', {}).get('type') == 'mcp_tool_call'
              and e['item'].get('server') == 'design-graph'
              and e['item'].get('status') == 'completed' and e['item'].get('error') is None
              and isinstance(e['item'].get('result'), dict)]
    for request in requests:
        if request.get('method') != 'tools/call':
            continue
        params = request['params']; result = response(request)
        if params['name'] not in names or result.get('isError', False) or not result.get('content'):
            continue
        if required_text and (params['name'] in {'list_screens', 'get_metrics'} or not any(
                required_text in part.get('text', '') for part in result['content'] if part.get('type') == 'text')):
            continue
        for item in native:
            if (item.get('tool') == params['name'] and item.get('arguments') == params.get('arguments', {})
                    and item['result'].get('content') == result['content']):
                return catalogue
    raise ValueError('no successful native MCP call matching real transcript and catalogue')


def validate_gate(root, python, worktree, *, version='v6-r2'):
    expected_protocol = protocol(version)
    folder = root/f'preflight-{version}'
    try:
        gate = json.loads((folder/'gate.json').read_text())
        if gate.get('protocol') != expected_protocol or gate.get('success') is not True:
            raise ValueError(f'unsuccessful {version} gate')
        binding = identity(python, worktree, root, version=version)
        if gate.get('freeze_sha256') != digest(root/'freeze.json'):
            raise ValueError('preflight freeze binding changed')
        if gate['identity'] != binding:
            raise ValueError('executor/model/config identity changed')
        if hashes(folder/'evidence') != gate['evidence_hashes']:
            raise ValueError('gate evidence changed')
        catalogue = evidence(folder/'evidence', required_text='Neutral Observatory', require_usage=version in {'v6','v6-r2'})
        if catalogue != json.loads((folder/'evidence/catalogue.json').read_text()):
            raise ValueError('catalogue differs from real response')
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f'valid successful {version} preflight required before any launch: {exc}') from exc


def preflight(root, python, worktree, *, version='v6-r2'):
    expected_protocol = protocol(version)
    from .gates import verify_freeze
    binding = identity(python,worktree,root,version=version)
    verify_freeze(root, Path(__file__).parent, binding)
    freeze_sha = digest(root/'freeze.json')
    from .gates import socket_precheck
    from .lifecycle import workspace, retire_preflight
    work = workspace(root, 'preflight')
    socket_precheck(work/'tmp')
    folder = fresh(root/f'preflight-{version}')
    proof = fresh(folder/'evidence'); state = work/'state'
    try:
        graph = fresh(work/'graph'); (work/'output').mkdir()
        source = work/'neutral.html'; source.write_text(FIXTURE)
        env = environment(work)
        env['CODEX_HOME'] = os.environ.get('CODEX_HOME', str(Path.home()/'.codex'))
        env['PYTHONPATH'] = str(worktree/'src'); env['GRAPH_DIR'] = str(graph)
        for key in ['OPENAI_API_KEY', 'OPENAI_BASE_URL', 'OPENAI_ORG_ID', 'OPENAI_PROJECT_ID']:
            env.pop(key, None)
        from .gates import socket_precheck
        write_json(proof/'tmpdir-check.json', socket_precheck(env['TMPDIR']))
        argv = index_command(python.parent, source, graph)
        write_json(proof/'index-command.json', argv)
        with (proof/'index.log').open('w') as log:
            proc = subprocess.Popen(argv, cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = proc.wait(timeout=TIME_LIMIT)
            finally:
                cleanup(proc)
        write_json(proof/'index-result.json', dict(exit_code=code, source_sha256=digest(source)))
        if code or guard_refusal((proof/'index.log').read_text()):
            raise ValueError('neutral index failed or refused; no retry')
        mcp_proof = fresh(state/'mcp')
        mcp = proxy(python, worktree, graph, mcp_proof)
        argv = command(work, state, mcp, env)
        prompt = ('Use a native design-graph MCP tool to inspect the indexed neutral.html fixture and report its heading. '
                  'Discover the available tools and make a useful read query. Do not use shell/Python to query the graph. '
                  'Work only inside this authorized physical workspace and its exclusive TMPDIR/caches. /tmp is permitted only within these paths; never global /tmp, parent or sibling. No destructive cleanup or rm -rf. No browser, browser automation, listener, server, framework, transpilation, web, apps, agents, installs, credentials or parent directories. '
                  'Any guard/policy refusal requires stopping the refused action immediately; never retry it through another API. '
                  'If MCP is unavailable, stop and report failure. Budget: 900 seconds, 120 tools.\n')
        (proof/'prompt.txt').write_text(prompt)
        write_json(proof/'command.json', dict(argv=argv, identity=binding, seconds=TIME_LIMIT, limit=TOOL_LIMIT))
        execute(argv, work, proof, prompt, env, seconds=TIME_LIMIT, limit=TOOL_LIMIT)
        from .audit import trace_gate
        events=[json.loads(line) for line in (proof/'events.jsonl').read_text().splitlines()]
        write_json(proof/'trace-audit.json', trace_gate(events,'B',work))
        write_json(proof/'catalogue.json', evidence(proof, required_text='Neutral Observatory', require_usage=version in {'v6','v6-r2'}))
        current = identity(python, worktree, root, version=version)
        if binding != current:
            raise ValueError('identity changed during preflight')
        write_json(folder/'gate.json', dict(protocol=expected_protocol, success=True, identity=binding, freeze_sha256=freeze_sha, evidence_hashes=hashes(proof)))
    except BaseException as exc:
        write_json(folder/'gate.json', dict(protocol=expected_protocol, success=False, diagnostic=str(exc), identity=binding))
        raise
    finally:
        # Success and failure preserve the same complete runtime bytes. Never clean collection.
        try:
            retire_preflight(root, freeze_sha)
        except BaseException as cleanup_error:
            write_json(folder/'cleanup-block.private.json', dict(diagnostic=str(cleanup_error), runtime_retained=True))
            gate=json.loads((folder/'gate.json').read_text())
            gate.update(success=False, cleanup_diagnostic=str(cleanup_error))
            write_json(folder/'gate.json',gate)
            raise
    return folder


def environment_template():
    from .runner import LOCAL_ENV_KEYS
    return dict(keys=sorted(LOCAL_ENV_KEYS), root='exact inventoried physical workspace', auth_home='inherited; never copied',
                limits='environment and prompt constrain controllable writes; trace QA mandatory; no total read/write isolation claim')
