"""Single B treatment inheriting an immutable v3 baseline; never launches A."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from .common import digest, environment, fresh, hashes, write_json
from .runner import TIME_LIMIT, TOOL_LIMIT, cleanup, command, execute, guard_refusal, index_command, proxy

CONDITION = '''\nCONDITION B: You MUST complete useful native design-graph MCP read queries covering EACH of the three screens in selection.json BEFORE writing any page output. Use each selected screen's key, label or component as the explicit name/screen argument; the returned content must contain relevant screen source or design information. Tool discovery/listing alone does not count. If MCP is unavailable or any screen cannot be queried, stop: the run is invalid. Any guard or policy refusal stops the action immediately; do not retry it through another API.\n'''


def verify_baseline(baseline):
    prep = baseline/'preparation'
    receipt = json.loads((prep/'freeze.json').read_text())
    actual = hashes(prep)
    actual.pop('freeze.json')
    if actual != receipt['files']:
        raise ValueError('baseline preparation differs from frozen file manifest')
    if hashes(prep/'agent-input') != receipt['input_hashes']:
        raise ValueError('baseline agent input differs from frozen manifest')
    # Historical instrument hashes describe provenance, not the revised v4 instrument.
    return dict(root=str(baseline), freeze_sha256=digest(prep/'freeze.json'), preparation_hashes=actual,
                historical_instrument_hashes=receipt.get('instrument_hashes', {}),
                inherited_A_evidence=hashes(baseline/'runs/A/evidence'),
                inherited_A_outputs=hashes(baseline/'runs/A/work/output'),
                historical_B_status='invalid; preserved; not reused',
                inherited_results={p.name:digest(p) for p in [baseline/'run-results.private.json', baseline/'evaluation-results.private.json'] if p.is_file()})


def graph_ready(graph, selected):
    """Setup-only readiness assertion; never substitutes for native session queries."""
    import kuzu
    from design_graph.model.graph.reader import GraphReader
    path = graph/'original.db'
    if not path.is_file() or not path.stat().st_size:
        raise ValueError('indexed graph missing or empty')
    database = kuzu.Database(str(path), read_only=True)
    connection = kuzu.Connection(database)
    try:
        reader = GraphReader(connection)
        if not reader.is_current_model():
            raise ValueError('indexed graph has incompatible model')
        screens = []
        for item in selected:
            screen = reader.get_screen(item['component'])
            component = reader.get_component_spec(item['component']) if not screen else None
            source = reader.get_full_source(item['component'])
            if (not source or not source.get('source_code', '').strip()
                    or (not screen and (not component or component.get('c.name') != item['component']))):
                raise ValueError('selected screen missing or empty in indexed graph')
            screens.append(dict(name=screen['name'] if screen else component['c.name'],
                                kind='screen' if screen else 'component',
                                components=screen['component_count'] if screen else len(component.get('children', [])),
                                source_chars=len(source['source_code'])))
        return dict(ready=True, screens=screens, graph_sha256=digest(path), read_only=True,
                    scope='setup assertion only; native MCP queries still required in B')
    finally:
        connection.close()
        database.close()


def run_b_v4(root, baseline, python, worktree):
    if root == baseline or baseline in root.parents or root in baseline.parents:
        raise ValueError('v4 scratch must be separate from baseline')
    from .preflight import validate_gate, identity, evidence as native_evidence
    validate_gate(root, python, worktree)  # before indexing, runs/, or any launch
    provenance = verify_baseline(baseline)
    if not provenance['inherited_A_evidence']:
        raise ValueError('missing inherited A evidence')
    if (root/'graph-B').exists(): raise ValueError('cold B graph already exists; no retry')
    runs = fresh(root/'runs'); lane = fresh(runs/'B')
    proof = fresh(lane/'evidence'); state = fresh(lane/'state')
    prep = baseline/'preparation'
    shutil.copytree(prep/'agent-input', lane/'work')
    shutil.copyfile(prep/'prompt.txt', lane/'prompt.txt')
    work = lane/'work'; (work/'output').mkdir()
    if hashes(lane/'work') != hashes(prep/'agent-input') or digest(lane/'prompt.txt') != digest(prep/'prompt.txt'):
        raise ValueError('baseline copy mismatch')
    write_json(proof/'provenance.json', provenance)
    write_json(proof/'identity.json', identity(python, worktree, root))
    (proof/'condition.txt').write_text(CONDITION)
    prompt = (lane/'prompt.txt').read_bytes().decode() + CONDITION
    env = environment(root); env['PYTHONPATH'] = str(worktree/'src'); env['GRAPH_DIR'] = str(root/'graph-B')
    env['CODEX_HOME'] = os.environ.get('CODEX_HOME', str(Path.home()/'.codex'))
    for key in ['OPENAI_API_KEY','OPENAI_BASE_URL','OPENAI_ORG_ID','OPENAI_PROJECT_ID']: env.pop(key, None)
    graph = fresh(root/'graph-B')
    selected = json.loads((work/'selection.json').read_text())
    if len(selected) != 3: raise ValueError('exactly three frozen selected screens required')
    build = index_command(python.parent, prep/'original.html', graph)
    started = time.monotonic()
    with (proof/'index.log').open('w') as log:
        proc = subprocess.Popen(build, cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try: code = proc.wait(timeout=TIME_LIMIT)
        finally: cleanup(proc)
    setup_seconds = time.monotonic()-started
    write_json(proof/'index.json', dict(argv=build, seconds=setup_seconds, exit_code=code,
               source_sha256=digest(prep/'original.html'), integral_original=True))
    if code or guard_refusal((proof/'index.log').read_text()): raise RuntimeError('index failed/refused; no alternative or retry')
    readiness_started = time.monotonic()
    write_json(proof/'graph-ready.json', graph_ready(graph, selected))
    readiness_seconds = time.monotonic()-readiness_started
    mcp = proxy(python, worktree, graph, proof)
    argv = command(work, state, mcp)
    write_json(proof/'command.json', dict(argv=argv, mcp=mcp, input_hashes=hashes(prep/'agent-input'),
               base_prompt_sha256=digest(lane/'prompt.txt'), seconds=TIME_LIMIT, limit=TOOL_LIMIT))
    result = execute(argv, work, proof, prompt, env, seconds=TIME_LIMIT, limit=TOOL_LIMIT, selections=selected)
    post = time.monotonic()
    result.update(setup_index_seconds=setup_seconds, readiness_seconds=readiness_seconds, valid=False, inherited_A=True)
    try:
        native_evidence(proof)  # successful turn + handshake/catalogue + native RPC match
        from .native_audit import covered_screens
        covered = covered_screens(proof, selected)
        if covered != {1,2,3} or result['queried_screen_indexes'] != [1,2,3]:
            raise ValueError('missing useful native queries for all three selected screens')
        if result['stop_reason'] or result['exit_code'] != 0: raise ValueError('executor stopped invalid')
        if any(not (work/'output'/f'page-{i}.html').is_file() for i in range(1,4)):
            raise ValueError('missing page output')
        if verify_baseline(baseline) != provenance: raise ValueError('baseline evidence changed')
        result['valid'] = True
    except BaseException as exc:
        result['invalid_reason'] = str(exc)
        raise
    finally:
        result['postprocessing_seconds'] = time.monotonic()-post
        result['timing_scope'] = 'main seconds: executor session only; setup/index, supervision cleanup and postprocessing separate'
        write_json(root/'run-results-v4.private.json', dict(protocol='iPede-3pages-v4-B-only', B=result,
                   A=dict(inherited=True, provenance_sha256=digest(proof/'provenance.json'))))
    if not result['valid']: raise RuntimeError('B invalid; retained; no fallback or retry')
    return result
