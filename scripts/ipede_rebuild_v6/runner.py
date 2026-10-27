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
from .common import digest, environment, fresh, hashes, write_json

LOCAL_ENV_KEYS = {'TMPDIR','TMP','TEMP','XDG_CACHE_HOME','XDG_CONFIG_HOME','XDG_DATA_HOME',
    'XDG_STATE_HOME','XDG_RUNTIME_DIR','NPM_CONFIG_CACHE','PIP_CACHE_DIR','UV_CACHE_DIR',
    'MPLCONFIGDIR','PYTHONPYCACHEPREFIX','SQLITE_TMPDIR','CUDA_CACHE_PATH','NODE_REPL_HISTORY'}

TIME_LIMIT = 900
TOOL_LIMIT = 120


def guard_refusal(text):
    import re
    return bool(re.search(r"(?i)(rejected by (?:policy|guard)|permission denied|operation not permitted|policy violation|approval required|requires? approval|not allowed by[^\n]{0,80}(?:policy|guard)|blocked by[^\n]{0,80}(?:policy|guard))", text))


TOOL_TYPES = {'command_execution','file_change','mcp_tool_call','dynamic_tool_call','web_search','image_generation','collab_tool_call'}


def executor_refusal(text):
    """Executor diagnostics only; returned tool/source JSON is never scanned here."""
    import re
    return guard_refusal(text) or bool(re.search(
        r'(?im)^.*ERROR codex_core::tools::router:.*(?:CreateProcess: Rejected:|exec_command failed:).*rejected:[^\n]*not permitted', text))


def config_files(cwd):
    home = Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex')))
    return sorted({Path('/etc/codex/config.toml'), Path('/etc/codex/managed_config.toml'),
                   home/'config.toml', *[p/'.codex/config.toml' for p in [cwd, *cwd.parents]]})


def inherited_servers(cwd):
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
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


def command(cwd, state, mcp=None, env=None):
    argv = ['codex','exec','--sandbox','workspace-write','-m','gpt-6.1-sol',
            '--json','--ephemeral','--skip-git-repo-check']
    config = ['model_reasoning_effort="medium"','web_search="disabled"',
              'features.apps=false','features.multi_agent=false','features.shell_snapshot=false','history.persistence="none"',
              f'log_dir={json.dumps(str(state/"logs"))}', f'sqlite_home={json.dumps(str(state/"sqlite"))}']
    if env is not None:
        config.append('shell_environment_policy.set={'+', '.join(k+'='+json.dumps(env[k]) for k in sorted(LOCAL_ENV_KEYS) if k in env)+'}')
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
        if env is not None:
            local = {k:v for k,v in env.items() if k in LOCAL_ENV_KEYS}
            config.append('mcp_servers.design-graph.env='+ '{'+', '.join(k+'='+json.dumps(v) for k,v in {**local, 'PYTHONPATH':mcp['pythonpath'], 'GRAPH_DIR':mcp['graph']}.items())+'}')
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
    operation_types, errors = {}, {}
    runtime = {Path(env[k]).relative_to(cwd).parts[0] for k in LOCAL_ENV_KEYS if k in env and Path(env[k]).is_relative_to(cwd)} | {'state'}
    def workspace_hashes():
        # Volatile executor state is runtime, not implementation. Avoid hashing live sqlite/caches.
        values = {}
        for path in sorted(cwd.rglob('*')):
            if path.relative_to(cwd).parts[0] in runtime: continue
            try:
                if path.is_file(): values[path.relative_to(cwd).as_posix()] = digest(path)
            except FileNotFoundError: pass
        return values
    initial_files = workspace_hashes()
    checkpoints = evidence/'checkpoints'; checkpoints.mkdir()
    workspace_previous = dict(initial_files)
    reason, proc = None, None
    mcp_events = {}
    matched_screens = set()
    session_end = None
    def sample_outputs():
        nonlocal reason, workspace_previous
        now = time.monotonic()
        # MCP writes only local runtime files. The supervisor copies immutable observations.
        for name in ['transcript.jsonl','server-stderr.log']:
            local = cwd/'state/mcp'/name
            if local.is_file(): shutil.copyfile(local,evidence/name)
        workspace_current = workspace_hashes()
        if workspace_current != workspace_previous:
            with (evidence/'workspace-writes.jsonl').open('a') as log:
                log.write(json.dumps({'seconds':now-start,
                    'changed':{k:v for k,v in workspace_current.items() if workspace_previous.get(k)!=v},
                    'removed':sorted(set(workspace_previous)-set(workspace_current))})+'\n')
            workspace_previous = workspace_current
        if selections and len(matched_screens) != len(selections):
            from .native_audit import covered_screens
            try:
                matched_screens.update(covered_screens(evidence, selections))
            except (OSError, ValueError, KeyError, TypeError):
                pass  # incomplete streaming records cannot open the gate
            implementation = lambda files: {k:v for k,v in files.items() if Path(k).parts[0] not in runtime}
            if len(matched_screens) != len(selections) and implementation(workspace_current) != implementation(initial_files):
                reason = reason or 'output_before_screen_queries'

        for path in sorted((cwd/'output').rglob('*')):
            name = str(path.relative_to(cwd/'output'))
            if path.is_file():
                stat = path.stat(); sig = (stat.st_mtime_ns, stat.st_size, digest(path))
                if signatures.get(name) != sig:
                    checkpoint = checkpoints/f'{len(list(checkpoints.iterdir())):05d}.bin'
                    shutil.copyfile(path, checkpoint)
                    signatures[name] = sig
                    item = writes.setdefault(name,dict(first_observed_seconds=now-start))
                    item.update(last_observed_seconds=now-start,sha256=sig[2],bytes=sig[1])

    with (evidence/'events.jsonl').open('w') as raw, (evidence/'observed-events.jsonl').open('w') as observed, (evidence/'stderr.log').open('wb') as err:
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
                if event.get('type') == 'turn.completed' and 'usage' in event: usage.append(event['usage'])
                item = event.get('item',{})
                # Only explicit failed tool diagnostics, never returned source content.
                diagnostic = item.get('error')
                if item.get('status') == 'failed' or item.get('exit_code') not in (None,0):
                    diagnostic = diagnostic or item.get('aggregated_output')
                if diagnostic and executor_refusal(json.dumps(diagnostic)):
                    reason = 'guard_refusal'
                    errors['diagnostic:event'] = dict(type='executor_guard_refusal', source='events.jsonl',
                        provenance='explicit failed tool diagnostic', diagnostic=diagnostic)
                if item.get('type') == 'mcp_tool_call':
                    event_type = event.get('type', 'unknown')
                    mcp_events[event_type] = mcp_events.get(event_type, 0) + 1
                if item.get('type') in TOOL_TYPES:
                    key = item.get('id')
                    if not key:
                        reason = reason or 'missing_operation_id'
                        continue
                    if key not in calls:
                        operation_types[item['type']] = operation_types.get(item['type'], 0) + 1
                    calls.add(key)
                    if (item.get('error') or item.get('status') == 'failed'
                        or item.get('exit_code') not in (None, 0)):
                        errors[key] = item
                    if len(calls)>limit and reason is None: reason='tool_limit'
                if item.get('type') in {'web_search','collab_tool_call'} and reason is None: reason='prohibited_tool'
        guard_tails = {}
        def inspect_guard(stream, block):
            nonlocal reason
            guard_tails[stream] = guard_tails.get(stream,b'') + block
            # Complete stream-specific lines only; no concatenation across streams.
            lines = guard_tails[stream].split(b'\n')
            guard_tails[stream] = lines.pop()
            for line in lines:
                check_line(stream, line)
            if stream is proc.stderr: check_line(stream, guard_tails[stream])
        def check_line(stream, line):
            nonlocal reason
            text = line.decode(errors='replace')
            if stream is proc.stdout:
                try: json.loads(line); return
                except (ValueError, UnicodeError): pass
            if executor_refusal(text):
                reason = 'guard_refusal'
                source = 'stderr.log' if stream is proc.stderr else 'events.jsonl'
                errors['diagnostic:'+source] = dict(type='executor_guard_refusal', source=source,
                    diagnostic=text, provenance='literal executor stream; no tool event inferred')
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
                        inspect_guard(key.fileobj, block)
                        if key.fileobj is proc.stderr:
                            err.write(block); err.flush()
                        else:
                            consume(block)
                    if reason: break
                    if proc.poll() is not None and not selector.get_map(): break
            finally:
                selector.close()
        except BaseException as exc:
            reason = type(exc).__name__
            errors['executor_exception'] = dict(type='executor_exception', diagnostic=str(exc))
        finally:
            session_end = time.monotonic()
            if proc:
                cleanup(proc)
                # Nonblocking bounded drain: do not wait for inherited pipe EOF.
                try:
                    tail = proc.stdout.read() or b''
                    consume(tail, final=True)
                    inspect_guard(proc.stdout, tail)
                except BlockingIOError:
                    pass
                sample_outputs()  # include writes made immediately before process exit
                try:
                    stderr_tail = proc.stderr.read() or b''
                except BlockingIOError:
                    stderr_tail = b''
                err.write(stderr_tail); err.flush()
                inspect_guard(proc.stderr, stderr_tail)
                for stream, tail in guard_tails.items(): check_line(stream, tail)
                proc.stderr.close()
                proc.stdout.close()
                write_json(evidence/'process.json',dict(pid=proc.pid,pgid=proc.pid,closed=True))
            try: usage_result = final_usage(usage)
            except ValueError as exc:
                usage_result = final_usage([])
                reason = reason or 'validation'
                errors['usage'] = dict(type='invalid_usage', diagnostic=str(exc))
            result = dict(seconds=session_end-start,supervision_seconds=time.monotonic()-session_end,
                queried_screen_indexes=sorted(matched_screens),stop_reason=reason,
                exit_code=proc.returncode if proc else None,tool_calls=len(calls),
                raw_mcp_item_events=mcp_events, operations_by_type=operation_types, errors=list(errors.values()),
                usage=usage_result, effective_context=None, money=None, fallback=None,
                time_limit_seconds=seconds,tool_limit=limit,raw_usage=usage,thread_ids=threads,
                output_artifact_observations=writes,observer_resolution_seconds=.05,
                accepted_timing=None,accepted_timing_reason='requires frozen functional evaluation; artifacts are not accepted pages',
                isolation='workspace-write sandbox; inherited policies; event access audit required')
            write_json(evidence/'metrics.json',result)
    return result



def final_usage(records):
    """Final turn usage only; cache is a subset of input, never extra input."""
    value = records[-1] if records else {}
    result = {k:value.get(k) for k in ['input_tokens','cached_input_tokens','output_tokens']}
    for n in result.values():
        if n is not None and (type(n) is not int or n < 0):
            raise ValueError('invalid usage')
    if (result['cached_input_tokens'] is not None and result['input_tokens'] is not None
            and result['cached_input_tokens'] > result['input_tokens']):
        raise ValueError('cached input exceeds total input')
    return result


def completed_usage(events):
    if any(e.get('type') in {'turn.failed','error'} for e in events):
        raise ValueError('native executor reported failure')
    completed=[e for e in events if e.get('type')=='turn.completed']
    if len(completed)!=1 or not isinstance(completed[0].get('usage'),dict):
        raise ValueError('one final completed native turn with usage required')
    usage=final_usage([completed[0]['usage']])
    if any(usage[k] is None for k in ['input_tokens','output_tokens']):
        raise ValueError('real final input/output usage required')
    return usage
