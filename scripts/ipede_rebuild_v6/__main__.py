"""Preparation CLI. Collection requires independent, exact-hash TL review."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys

from .common import fresh, write_json, digest, hashes
from .gates import freeze, verify_freeze, approval, manifest
from .preflight import identity, preflight, validate_gate
from .protocol import ORDER, prompt


def collect(root, worktree):
    """Downstream only; no launch is possible with pending TL approval."""
    python=Path(sys.executable); binding=identity(python,worktree,root)
    approval(root,Path(__file__).parent,binding)
    validate_gate(root,python,worktree,version='v6')
    prep=root/'preparation'
    # Functional oracle and setup readiness are separate mandatory gates.
    if json.loads((prep/'oracle/receipt.json').read_text()).get('passed') is not True:
        raise ValueError('private real oracle required')
    if json.loads((prep/'readiness.private.json').read_text()).get('ready') is not True:
        raise ValueError('integral graph readiness required')
    targets=json.loads((prep/'targets.private.json').read_text())
    graph_path=Path(json.loads((prep/'setup.private.json').read_text())['graph'])
    if digest(graph_path) != json.loads((prep/'readiness.private.json').read_text())['graph_sha256']:
        raise ValueError('integral indexed graph changed')
    graph=graph_path.parent
    sessions=fresh(root/'sessions')  # no retry, even when an earlier attempt failed
    from .runner import command, execute, proxy
    from .common import environment
    from .audit import copy_scan, trace_gate
    from .preflight import evidence
    env=environment(root)
    env['PYTHONPATH']=str(worktree/'src'); env['GRAPH_DIR']=str(graph)
    for key in ['OPENAI_API_KEY','OPENAI_BASE_URL','OPENAI_ORG_ID','OPENAI_PROJECT_ID']: env.pop(key,None)
    for page,lane in ORDER:
        verify_freeze(root,Path(__file__).parent,identity(python,worktree,root))
        session=fresh(sessions/f'{page}-{lane}'); proof=fresh(session/'evidence'); state=fresh(session/'state')
        work=session/'work'; shutil.copytree(prep/'agent-input',work); (work/'output').mkdir()
        t=targets[page-1]
        # Only title and state enter common input. Native semantic names can be
        # discovered by B; original module names/locations are private.
        write_json(work/'target.json',{'title':t['title'],'state':t['state']})
        supplied = hashes(work)
        supplied.pop('target.json')
        if supplied != hashes(prep/'agent-input'):
            raise ValueError('asymmetric source/assets input')
        mcp=proxy(python,worktree,graph,proof) if lane=='B' else None
        argv=command(work,state,mcp)
        write_json(proof/'command.json',{'argv':argv,'input_hashes':hashes(work),
                   'prompt_sha256':digest(prep/f'prompt-{lane}.txt'),'freeze_sha256':digest(root/'freeze.json')})
        result=execute(argv,work,proof,prompt(lane),env,selections=[t] if lane=='B' else None)
        if result['stop_reason'] or result['exit_code']:
            raise ValueError('collection stopped; retain evidence, never retry')
        if lane=='B': evidence(proof,require_usage=True)
        from .runner import final_usage
        final_usage(result['raw_usage'])
        output=work/'output/page.html'
        if [p.name for p in (work/'output').iterdir()] != ['page.html']:
            raise ValueError('exactly one HTML required')
        events=[json.loads(x) for x in (proof/'events.jsonl').read_text().splitlines()]
        from .runner import completed_usage
        completed_usage(events)
        if hashes(prep/'agent-input') != {k:digest(work/k) for k in hashes(prep/'agent-input')}:
            raise ValueError('supplied source/assets mutated')
        write_json(proof/'trace-audit.json',trace_gate(events,lane,work))
        write_json(proof/'copy-audit.json',copy_scan(work/'input/original.html',output))
        write_json(proof/'acceptance.json',{'valid':None,'manual_review_required':True,
                   'evaluation_seconds':None,'generation_seconds':result['seconds']})


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','freeze','preflight','validate','collect','materialize','manifest'])
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--source',type=Path); parser.add_argument('--plans',type=Path)
    parser.add_argument('--targets',type=Path); parser.add_argument('--graph',type=Path)
    args=parser.parse_args(); root=args.root.resolve(); worktree=Path.cwd().resolve()
    if args.action=='prepare':
        if not all([args.source,args.plans,args.targets]): parser.error('prepare requires source, plans, targets')
        from .prepare import prepare
        prepare(root,args.source,args.plans,args.targets,args.graph)
        for lane in ['A','B']: (root/f'preparation/prompt-{lane}.txt').write_text(prompt(lane))
    elif args.action=='freeze':
        from .rubric import verify_references
        verify_references(root/'preparation',json.loads((root/'preparation/rubric.private.json').read_text()))
        for rel, key in [('oracle/receipt.json','passed'),('readiness.private.json','ready')]:
            if json.loads((root/'preparation'/rel).read_text()).get(key) is not True:
                raise ValueError('real preparation evidence required before freeze')
        print(freeze(root,Path(__file__).parent,identity(Path(sys.executable),worktree,root)))
    elif args.action=='preflight':
        preflight(root,Path(sys.executable),worktree,version='v6')
    elif args.action=='validate':
        approval(root,Path(__file__).parent,identity(Path(sys.executable),worktree,root))
        validate_gate(root,Path(sys.executable),worktree,version='v6')
    elif args.action=='collect': collect(root,worktree)
    elif args.action=='materialize':
        from .results import materialize
        materialize(root, root/'results')
    elif args.action=='manifest': print(manifest(root))


if __name__=='__main__': main()
