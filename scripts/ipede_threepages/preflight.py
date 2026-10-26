"""v4 neutral, single-attempt native MCP gate. No collection is started here."""
from __future__ import annotations
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess

from .common import digest, environment, fresh, hashes, write_json
from .runner import TIME_LIMIT, TOOL_LIMIT, cleanup, command, execute, guard_refusal, index_command, proxy, config_files

PROTOCOL = 'iPede-3pages-v4-preflight'


def protocol(version):
    if version not in {'v4', 'v5'}:
        raise ValueError('unsupported preflight version')
    return f'iPede-3pages-{version}-preflight'

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


def identity(python, worktree, root, *, version='v4'):
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
    files = [real_binary, Path(shutil.which('node') or executor), *config_files(root), Path(executor), Path(python), python.parent/'design-mcp', python.parent/'design-graph', home/'config.toml']
    # Bind inherited local policies/configuration without retaining their contents or auth.
    for parent in [worktree, *worktree.parents, root, *root.parents]:
        files += [parent/'AGENTS.md', parent/'AGENTS.override.md', parent/'.codex/config.toml']
    files += [home/'AGENTS.md', home/'AGENTS.override.md']
    files += sorted((home/'rules').glob('*.rules'))
    files += sorted((worktree/'.codex/rules').glob('*.rules'))
    payload = dict(protocol=protocol(version), executor=str(launcher), real_binary=str(real_binary), python=str(python),
                   worktree=str(worktree), codex_home=str(home), seconds=TIME_LIMIT, limit=TOOL_LIMIT,
                   command=command(root/'<work>', Path('<state>'), proxy(python, worktree, Path('<graph>'), Path('<evidence>'))),
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
        for event in (e for e in events if e.get('type') == 'turn.completed'):
            usage = event.get('usage')
            if not isinstance(usage, dict) or not all(
                    type(usage.get(key)) in {int, float} and usage[key] >= 0
                    and (type(usage[key]) is int or math.isfinite(usage[key]))
                    for key in ('input_tokens', 'output_tokens')):
                raise ValueError('completed native turn requires numeric input/output usage')
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


def validate_gate(root, python, worktree, *, version='v4'):
    expected_protocol = protocol(version)
    folder = root/f'preflight-{version}'
    try:
        gate = json.loads((folder/'gate.json').read_text())
        if gate.get('protocol') != expected_protocol or gate.get('success') is not True:
            raise ValueError(f'unsuccessful {version} gate')
        binding = identity(python, worktree, root) if version == 'v4' else identity(python, worktree, root, version=version)
        if gate['identity'] != binding:
            raise ValueError('executor/model/config identity changed')
        if hashes(folder/'evidence') != gate['evidence_hashes']:
            raise ValueError('gate evidence changed')
        catalogue = evidence(folder/'evidence', required_text='Neutral Observatory', require_usage=version == 'v5')
        if catalogue != json.loads((folder/'evidence/catalogue.json').read_text()):
            raise ValueError('catalogue differs from real response')
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f'valid successful {version} preflight required before any launch: {exc}') from exc


def preflight(root, python, worktree, *, version='v4'):
    expected_protocol = protocol(version)
    folder = fresh(root/f'preflight-{version}')
    proof = fresh(folder/'evidence'); work = fresh(folder/'work'); state = fresh(folder/'state')
    graph = fresh(folder/'graph'); (work/'output').mkdir()
    source = work/'neutral.html'; source.write_text(FIXTURE)
    binding = identity(python, worktree, root) if version == 'v4' else identity(python, worktree, root, version=version)
    env = environment(root)
    env['CODEX_HOME'] = os.environ.get('CODEX_HOME', str(Path.home()/'.codex'))
    env['PYTHONPATH'] = str(worktree/'src'); env['GRAPH_DIR'] = str(graph)
    for key in ['OPENAI_API_KEY', 'OPENAI_BASE_URL', 'OPENAI_ORG_ID', 'OPENAI_PROJECT_ID']:
        env.pop(key, None)
    try:
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
        mcp = proxy(python, worktree, graph, proof)
        argv = command(work, state, mcp)
        prompt = ('Use a native design-graph MCP tool to inspect the indexed neutral.html fixture and report its heading. '
                  'Discover the available tools and make a useful read query. Do not use shell/Python to query the graph. '
                  'Work only here; no web, apps, agents, installs, credentials or parent directories. '
                  'Any guard/policy refusal requires stopping the refused action immediately; never retry it through another API. '
                  'If MCP is unavailable, stop and report failure. Budget: 900 seconds, 90 tools.\n')
        (proof/'prompt.txt').write_text(prompt)
        write_json(proof/'command.json', dict(argv=argv, identity=binding, seconds=TIME_LIMIT, limit=TOOL_LIMIT))
        execute(argv, work, proof, prompt, env, seconds=TIME_LIMIT, limit=TOOL_LIMIT)
        write_json(proof/'catalogue.json', evidence(proof, required_text='Neutral Observatory', require_usage=version == 'v5'))
        current = identity(python, worktree, root) if version == 'v4' else identity(python, worktree, root, version=version)
        if binding != current:
            raise ValueError('identity changed during preflight')
        write_json(folder/'gate.json', dict(protocol=expected_protocol, success=True, identity=binding, evidence_hashes=hashes(proof)))
    except BaseException as exc:
        write_json(folder/'gate.json', dict(protocol=expected_protocol, success=False, diagnostic=str(exc), identity=binding))
        raise
    return folder
