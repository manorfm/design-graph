"""Run the required neutral validations in a fresh exclusive scratch subtree.

No preflight, collection, approval, release or publication. Preserve every attempt.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from scripts.ipede_rebuild_v6.common import digest, environment, fresh, write_json
from scripts.ipede_rebuild_v6.gates import safe_hashes
from scripts.ipede_rebuild_v6.lifecycle import owned, physical
from scripts.ipede_rebuild_v6.preflight import FIXTURE


def source_fingerprint(repo):
    return dict(trees={name:safe_hashes(repo/name) for name in ['scripts','tests','src']},
        files={name:digest(repo/name) for name in ['pyproject.toml','Makefile','docs/experiments/ipede-rebuild-v6-r2-tmp-v1.freeze.schema.json']})


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scratch',type=Path,required=True)
    args=parser.parse_args(); scratch=physical(args.scratch); owned(scratch)
    repo=Path.cwd(); run=fresh(scratch/f'validation-{time.time_ns()}')
    sources=source_fingerprint(repo)
    env=environment(scratch)
    env['PYTHONPATH']=str(repo)+os.pathsep+str(repo/'src')
    env['PATH']=str(Path(sys.executable).parent)+os.pathsep+env['PATH']
    (run/'neutral.html').write_text(FIXTURE)
    commands=[('focal-sealed.log',[sys.executable,'-m','pytest','tests/unit/scripts/test_ipede_rebuild_v6.py','tests/unit/scripts/test_ipede_tmp_v1.py','-q','-p','no:cacheprovider','--basetemp',str(run/'focal-tests')]),
        ('pytest-sealed.log',[sys.executable,'-m','pytest','-q','-p','no:cacheprovider','--basetemp',str(run/'full-tests')]),
        ('make-build.log',['make','build','PROTO='+str(run/'neutral.html'),'DB_DIR='+str(run/'build'),'GRAPH_DB='+str(run/'build/neutral.db')]),
        ('diff-check.log',['git','diff','--check'])]
    results=[]
    for name,argv in commands:
        with (run/name).open('x') as log:
            code=subprocess.run(argv,env=env,stdout=log,stderr=subprocess.STDOUT).returncode
        results.append(dict(log=str((run/name).relative_to(scratch)),argv=argv,exit_code=code))
        write_json(run/'commands.private.json',results)
        print(name,code,flush=True)
        if code: raise SystemExit(code)
    # Compare exact protected source with the authorized base, without reading private history.
    protected={}
    for name,functions in [('gates.py',['socket_precheck']),('runner.py',['guard_refusal','executor_refusal','command'])]:
        path='scripts/ipede_rebuild_v6/'+name
        before=subprocess.check_output(['git','show','d31afe8:'+path],text=True)
        after=(repo/path).read_text()
        for function in functions:
            def source(text):
                node=next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name==function)
                return ''.join(text.splitlines(keepends=True)[node.lineno-1:node.end_lineno])
            old,new=source(before),source(after)
            if old != new: raise ValueError('protected function changed: '+function)
            protected[function]=hashlib.sha256(new.encode()).hexdigest()
    for name in ['rubric.public.json','rubric.schema.json','oracle.py','protocol.py']:
        path='scripts/ipede_rebuild_v6/'+name
        original=subprocess.check_output(['git','show','d31afe8:'+path])
        actual=(repo/path).read_bytes()
        if name != 'protocol.py' and original != actual: raise ValueError('rubric/oracle changed')
        protected[name]=dict(base=hashlib.sha256(original).hexdigest(),current=hashlib.sha256(actual).hexdigest())
    write_json(run/'integrity.private.json',protected)
    if sources != source_fingerprint(repo): raise ValueError('sources changed during validation; cannot seal')
    write_json(run/'sources.private.json',sources)
    write_json(scratch/'validation-commands.private.json',results)
    write_json(scratch/'validation-latest.private.json',dict(run=str(run),integrity=str(run/'integrity.private.json'),sources=str(run/'sources.private.json')))


if __name__=='__main__': main()
