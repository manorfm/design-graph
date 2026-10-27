"""Reproduce R2 custody from immutable preparation; no executor or collection.

Private paths are CLI arguments, never published. Build a fresh integral index.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

from scripts.ipede_rebuild_v6.common import fresh, hashes, digest, write_json
from scripts.ipede_rebuild_v6.protocol import prompt
from scripts.ipede_rebuild_v6.prepare import graph_ready
from scripts.ipede_rebuild_v6.rubric import verify_references


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['previous','root','scratch']:parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args(); old=args.previous;root=fresh(args.root);prep=fresh(root/'preparation')
    # Explicit allowlist: no approvals, sessions, outputs or preflight inheritance.
    names=['agent-input','oracle','oracle-local-actions','oracle-variants','functional-plan.private.json',
           'targets.private.json','rubric.private.json','negative-inspection.private.json']
    original={}
    for name in names:
        source=old/name;target=prep/name
        if source.is_dir():
            if any(p.is_symlink() for p in source.rglob('*')):raise ValueError('symlink in immutable input')
            shutil.copytree(source,target); original.update({name+'/'+k:v for k,v in hashes(source).items()})
        else:shutil.copyfile(source,target);original[name]=digest(source)
    if hashes(prep)!=original:raise ValueError('copy hash mismatch')
    rubric=json.loads((prep/'rubric.private.json').read_text())
    # Inspect all references before validation; never rewrite oracle assertions.
    refs=[c['reference'][k] for r in rubric['rows'] for cs in r['checks'].values() for c in cs for k in ['dom','image']]
    absolute=[v for v in refs if Path(v).is_absolute()]
    if absolute:raise ValueError('absolute reference requires explicit hash-preserving mapping; no rewrite')
    verify_references(prep,rubric)
    for lane in ['A','B']:(prep/f'prompt-{lane}.txt').write_text(prompt(lane))
    index=fresh(args.scratch/'index');graph=index/'original.db'
    source=prep/'agent-input/input/original.html'
    argv=[str(Path(sys.executable).parent/'design-graph'),str(source),'--db',str(graph)]
    started=time.monotonic()
    with (args.scratch/'index.log').open('x') as log:
        subprocess.run(argv,cwd=Path.cwd(),stdout=log,stderr=subprocess.STDOUT,check=True,timeout=900)
    seconds=time.monotonic()-started
    readiness=graph_ready(graph,json.loads((prep/'targets.private.json').read_text()))
    write_json(prep/'readiness.private.json',readiness)
    write_json(prep/'setup.private.json',dict(graph=str(graph),index_seconds=seconds,reused_setup_index=False,
        reused_oracle_seconds=None,source_sha256=digest(source),inputs=hashes(prep/'agent-input')))
    write_json(prep/'provenance.private.json',dict(previous=str(old),reused=True,reused_setup_seconds=None,
        immutable_hashes=original,absolute_references=absolute,index_command=argv,
        exclusions=['approvals','preflight','sessions','outputs']))
    (root/'TL-approval.json').write_text('{}\n')


if __name__=='__main__':main()
