"""Serial single-attempt runner. No invocation occurs at import or preparation."""
from __future__ import annotations
import json
import os
import selectors
import shutil
import signal
import subprocess
import time
from pathlib import Path
from .common import digest, environment, fresh, hashes, verify, write_json

TIME_LIMIT = 900
TOOL_LIMIT = 90


def guard_refusal(text):
    import re
    return bool(re.search(r"(?i)(rejected by (?:policy|guard)|permission denied|operation not permitted|policy violation|approval required|requires? approval|not allowed by[^\n]{0,80}(?:policy|guard)|blocked by[^\n]{0,80}(?:policy|guard))", text))


TOOL_TYPES = {'command_execution','file_change','mcp_tool_call','dynamic_tool_call','web_search','image_generation','collab_tool_call'}


def config_files(cwd):
    home = Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex')))
    return sorted({Path('/etc/codex/config.toml'), Path('/etc/codex/managed_config.toml'),
                   home/'config.toml', *[p/'.codex/config.toml' for p in [cwd, *cwd.parents]]})


def inherited_servers(cwd):
    import tomllib
    names = set()
    def visit(value):
        if not isinstance(value, dict): return
        names.update(value.get('mcp_servers', {}))
        for child in value.values(): visit(child)
    for path in config_files(cwd):
        if path.is_file(): visit(tomllib.loads(path.read_text()))
    return sorted(names)


def proxy(python, worktree, graph, evidence):
    return dict(command=str(python), args=[str(Path(__file__).with_name('stdio_recorder.py').resolve()),
                str(evidence/'transcript.jsonl'), str(evidence/'server-stderr.log'), str(python.parent/'design-mcp')],
                pythonpath=str(worktree/'src'), graph=str(graph))


def command(cwd, state, mcp=None):
    argv = ['codex','exec','--sandbox','workspace-write','-m','gpt-6.1-sol',
            '--json','--ephemeral','--skip-git-repo-check']
    config = ['model_reasoning_effort="medium"','web_search="disabled"',
              'features.apps=false','features.multi_agent=false','history.persistence="none"',
              f'log_dir={json.dumps(str(state/"logs"))}', f'sqlite_home={json.dumps(str(state/"sqlite"))}']
    import re
    servers = inherited_servers(cwd)
    if any(not re.fullmatch(r'[A-Za-z0-9_-]+', name) for name in servers):
        raise ValueError('inherited MCP name cannot be safely represented by CLI dotted overrides')
    config += [f'mcp_servers.{name}.enabled=false' for name in servers]
    if mcp is None:
        config.append('mcp_servers={}')
    else:
        # Actual installed design-mcp console entry point, importing this worktree.
        config += ['mcp_servers.design-graph.enabled=true', f'mcp_servers.design-graph.command={json.dumps(mcp["command"])}',
                   'mcp_servers.design-graph.env={PYTHONPATH='+json.dumps(mcp['pythonpath'])+', GRAPH_DIR='+json.dumps(mcp['graph'])+'}',
                   'mcp_servers.design-graph.startup_timeout_sec=120']
        if mcp.get('args'):
            config.append('mcp_servers.design-graph.args='+json.dumps(mcp['args']))
    for value in config:
        argv += ['-c',value]
    return argv+['-C',str(cwd),'-']


def index_command(bindir, source, graph):
    # The installed CLI accepts the source directly, and --db (not --out).
    return [str(bindir/'design-graph'), str(source), '--db', str(graph/'original.db')]


def cleanup(proc):
    """Bounded cleanup even if descendants retain stdout or ignore TERM."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait(timeout=2)


def execute(argv, cwd, evidence, prompt, env, seconds=TIME_LIMIT, limit=TOOL_LIMIT, selections=None):
    start = time.monotonic()
    writes, signatures, calls, usage, threads = {}, {}, set(), [], []
    reason, proc = None, None
    mcp_events = {}
    matched_screens = set()
    session_end = None
    def sample_outputs():
        nonlocal reason
        now = time.monotonic()
        if selections and len(matched_screens) != 3:
            from .native_audit import covered_screens
            try:
                matched_screens.update(covered_screens(evidence, selections))
            except (OSError, ValueError, KeyError, TypeError):
                pass  # incomplete streaming records cannot open the gate
            if len(matched_screens) != 3 and any((cwd/'output').rglob('*')):
                reason = reason or 'output_before_screen_queries'

        for name in ['page-1.html','page-2.html','page-3.html']:
            path = cwd/'output'/name
            if path.is_file():
                stat = path.stat(); sig = (stat.st_mtime_ns, stat.st_size, digest(path))
                if signatures.get(name) != sig:
                    signatures[name] = sig
                    item = writes.setdefault(name,dict(first_observed_seconds=now-start))
                    item.update(last_observed_seconds=now-start,sha256=sig[2],bytes=sig[1])

    with (evidence/'events.jsonl').open('w') as raw, (evidence/'observed-events.jsonl').open('w') as observed, (evidence/'stderr.log').open('w') as err:
        pending = b''
        def consume(block, final=False):
            nonlocal pending, reason
            sample_outputs()  # fail closed before accepting newly received native completions
            raw.write(block.decode(errors='replace')); raw.flush()
            pending += block
            lines = pending.split(b'\n')
            pending = lines.pop()
            if final and pending:
                lines.append(pending); pending = b''
            for line in lines:
                try: event = json.loads(line)
                except (ValueError,UnicodeError): continue
                observed.write(json.dumps(dict(received_monotonic=time.monotonic(),event=event))+'\n'); observed.flush()
                if event.get('type') == 'thread.started': threads.append(event.get('thread_id'))
                if 'usage' in event: usage.append(event['usage'])
                item = event.get('item',{})
                if item.get('type') == 'mcp_tool_call':
                    event_type = event.get('type', 'unknown')
                    mcp_events[event_type] = mcp_events.get(event_type, 0) + 1
                if item.get('type') in TOOL_TYPES:
                    key = item.get('id') or json.dumps(item,sort_keys=True)
                    calls.add(key)
                    if len(calls)>=limit and reason is None: reason='tool_limit'
                if item.get('type') in {'web_search','collab_tool_call'} and reason is None: reason='prohibited_tool'
        try:
            proc = subprocess.Popen(argv,cwd=cwd,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,start_new_session=True)
            write_json(evidence/'process.json',dict(pid=proc.pid,pgid=proc.pid,closed=False))
            proc.stdin.write(prompt.encode()); proc.stdin.close()
            os.set_blocking(proc.stdout.fileno(),False)
            os.set_blocking(proc.stderr.fileno(),False)
            selector = selectors.DefaultSelector()
            selector.register(proc.stdout,selectors.EVENT_READ)
            selector.register(proc.stderr,selectors.EVENT_READ)
            guard_tail = ""
            try:
                while True:
                    sample_outputs()
                    if reason: break
                    server_err = evidence/'server-stderr.log'
                    if server_err.is_file() and guard_refusal(server_err.read_text()):
                        reason = 'guard_refusal'; break
                    elapsed = time.monotonic()-start
                    if elapsed >= seconds:
                        reason = 'timeout'; break
                    ready = selector.select(min(.05,max(0,seconds-elapsed)))
                    for key, _ in ready:
                        block = os.read(key.fileobj.fileno(),65536)
                        if not block:
                            selector.unregister(key.fileobj)
                            continue
                        guard_tail = (guard_tail + block.decode(errors='replace'))[-131072:]
                        if guard_refusal(guard_tail): reason = 'guard_refusal'
                        if key.fileobj is proc.stderr:
                            err.write(block.decode(errors='replace')); err.flush()
                        else:
                            consume(block)
                    if reason: break
                    if proc.poll() is not None and not selector.get_map(): break
            finally:
                selector.close()
        except BaseException as exc:
            reason = type(exc).__name__
            raise
        finally:
            session_end = time.monotonic()
            if proc:
                cleanup(proc)
                # Nonblocking bounded drain: do not wait for inherited pipe EOF.
                try:
                    tail = proc.stdout.read() or b''
                    consume(tail, final=True)
                    if guard_refusal(tail.decode(errors='replace')): reason = 'guard_refusal'
                except BlockingIOError:
                    pass
                sample_outputs()  # include writes made immediately before process exit
                try:
                    stderr_tail = proc.stderr.read() or b''
                except BlockingIOError:
                    stderr_tail = b''
                err.write(stderr_tail.decode(errors='replace')); err.flush()
                if guard_refusal((evidence/'stderr.log').read_text()): reason = 'guard_refusal'
                proc.stderr.close()
                proc.stdout.close()
                write_json(evidence/'process.json',dict(pid=proc.pid,pgid=proc.pid,closed=True))
            result = dict(seconds=session_end-start,supervision_seconds=time.monotonic()-session_end,
                queried_screen_indexes=sorted(matched_screens),stop_reason=reason,
                exit_code=proc.returncode if proc else None,tool_calls=len(calls),
                raw_mcp_item_events=mcp_events,
                time_limit_seconds=seconds,tool_limit=limit,raw_usage=usage,thread_ids=threads,
                output_artifact_observations=writes,observer_resolution_seconds=.05,
                accepted_timing=None,accepted_timing_reason='requires frozen functional evaluation; artifacts are not accepted pages',
                isolation='workspace-write sandbox; inherited policies; event access audit required')
            write_json(evidence/'metrics.json',result)
    return result


def run(root, approval):
    preparation = root/'preparation'
    verify(preparation)
    decision = json.loads(Path(approval).read_text())
    if decision.get('freeze_sha256') != digest(preparation/'freeze.json') or decision.get('approved') is not True:
        raise ValueError('parent approval must identify exact freeze SHA256')
    if (root/'graph-B').exists():
        raise ValueError('cold B graph directory already exists')
    if not decision.get('scope_decision'):
        raise ValueError('parent must record route scope/median/placeholder decision')
    from .preflight import validate_gate
    runtime = json.loads((preparation/'environment.json').read_text())
    validate_gate(root, Path(runtime['python']), Path(runtime['worktree']))
    runs = fresh(root/'runs')  # no implicit retry, even after interrupted/failed attempt
    worktree = Path(runtime['worktree']); bindir = Path(runtime['python']).parent
    base_env = environment(root)
    base_env['PYTHONPATH'] = str(worktree/'src')
    base_env['CODEX_HOME'] = os.environ.get('CODEX_HOME',str(Path.home()/'.codex'))
    for key in ['OPENAI_API_KEY','OPENAI_BASE_URL','OPENAI_ORG_ID','OPENAI_PROJECT_ID']:
        base_env.pop(key,None)
    results = {}
    for lane in ['A','B']:
        cwd = fresh(runs/lane); shutil.copytree(preparation/'agent-input',cwd/'work')
        work = cwd/'work'; (work/'output').mkdir(); state=fresh(cwd/'state'); evidence=fresh(cwd/'evidence')
        env=dict(base_env);env['GRAPH_DIR']=str(root/'graph-B')
        mcp = None
        if lane=='B':
            # Cold graph build is separate from B's agent budget and also included in total.
            start=time.monotonic()
            build_argv=index_command(bindir, preparation/'original.html', root/'graph-B')
            with (evidence/'index.log').open('w') as log:
                p=subprocess.Popen(build_argv,cwd=work,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                try: code=p.wait(timeout=900)
                except subprocess.TimeoutExpired:
                    cleanup(p);code=p.returncode
                finally: cleanup(p)
            write_json(evidence/'index.json',dict(seconds=time.monotonic()-start,exit_code=code,argv=build_argv,cold=True))
            if code: raise RuntimeError('B cold index failed; retained, no retry')
            mcp=dict(command=str(bindir/'design-mcp'),pythonpath=str(worktree/'src'),graph=env['GRAPH_DIR'])
        argv=command(work,state,mcp)
        write_json(evidence/'command.json',dict(argv=argv,cwd=str(work),input_hashes=hashes(work),
            credential_contents_accessed_by_instrument=False,auth='existing CODEX_HOME OAuth; no API key',mcp=mcp))
        prompt=(preparation/'prompt.txt').read_text()
        results[lane]=execute(argv,work,evidence,prompt,env)
        if lane=='B':
            results[lane]['cold_index_seconds']=json.loads((evidence/'index.json').read_text())['seconds']
            results[lane]['total_seconds']=results[lane]['seconds']+results[lane]['cold_index_seconds']
        else: results[lane]['total_seconds']=results[lane]['seconds']
        write_json(root/'run-results.private.json',results)
        if results[lane]['stop_reason'] or results[lane]['exit_code'] != 0:
            raise RuntimeError('collection stopped; failure retained, no retry or alternate executor')
    from .audit import audit
    audit(root)
    return results
