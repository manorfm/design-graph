"""Seal tmp-v1 after validation, before the one separately invoked preflight.

Private CLI paths never enter the public receipt. No collection or approval.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import jsonschema
from scripts.ipede_rebuild_v6.common import CONTRACT, digest, write_json
from scripts.ipede_rebuild_v6.failures import POLICY
from scripts.ipede_rebuild_v6.gates import freeze, manifest, public_document, socket_precheck, verify_freeze
from scripts.ipede_rebuild_v6.lifecycle import validate
from scripts.ipede_rebuild_v6.preflight import identity
from scripts.ipede_rebuild_v6.protocol import ORDER
from scripts.ipede_rebuild_v6.rubric import verify_references


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--scratch', type=Path, required=True)
    args = parser.parse_args(); root=args.root; scratch=args.scratch; worktree=Path.cwd()
    data=validate(root, allow_retired=False)
    if data['scratch']['path'] != str(scratch): raise ValueError('scratch mismatch')
    if (root/'freeze.json').exists(): raise ValueError('already sealed')
    prep=root/'preparation'; instrument=worktree/'scripts/ipede_rebuild_v6'
    verify_references(prep,json.loads((prep/'rubric.private.json').read_text()))
    for rel, key in [('oracle/receipt.json','passed'),('readiness.private.json','ready')]:
        if json.loads((prep/rel).read_text()).get(key) is not True: raise ValueError('real oracle/index required')
    graph=Path(json.loads((prep/'setup.private.json').read_text())['graph'])
    if digest(graph) != json.loads((prep/'readiness.private.json').read_text())['graph_sha256']:
        raise ValueError('index changed')
    for path in data['workspaces'].values(): socket_precheck(Path(path)/'tmp')
    commands=json.loads((scratch/'validation-commands.private.json').read_text())
    if len(commands) != 4 or any(item['exit_code'] != 0 for item in commands): raise ValueError('validation failed')
    if {Path(item['log']).name for item in commands} != {'focal-sealed.log','pytest-sealed.log','make-build.log','diff-check.log'}:
        raise ValueError('required validations missing')
    names=['install.log','preparation.log',*[item['log'] for item in commands]]
    for name in names:
        path=(scratch/name)
        from scripts.ipede_rebuild_v6.lifecycle import physical
        physical(path)
        if not path.is_relative_to(scratch) or not path.is_file(): raise ValueError('validation log outside scratch/missing')
        if Path(name).name in {'focal-sealed.log','pytest-sealed.log'}:
            if not re.search(r'(?m)^.*\d+ passed.* in ',path.read_text()): raise ValueError('passing summary missing')
    latest=json.loads((scratch/'validation-latest.private.json').read_text())
    from scripts.validate_ipede_tmp_v1 import source_fingerprint
    sources=physical(latest['sources'])
    if not sources.is_relative_to(scratch) or json.loads(sources.read_text()) != source_fingerprint(worktree):
        raise ValueError('sources changed after validation; cannot seal')
    integrity=physical(latest['integrity'])
    if not integrity.is_relative_to(scratch): raise ValueError('outside scratch integrity')
    write_json(prep/'validation.private.json',dict(logs={n:digest(scratch/n) for n in names},
        integrity_sha256=digest(integrity),sources_sha256=digest(sources),commands=commands))
    write_json(prep/'failure-policy.private.json',POLICY)
    write_json(prep/'workspace.private.json',dict(worktree=str(worktree),python=str(Path(sys.executable)),
        venv=str(Path(sys.executable).parent.parent),git_head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()))
    write_json(prep/'positions.initial.private.json',[dict(page=p,lane=l,status='not_started',reason='pending_TL',artifact=None,accepted=None) for p,l in ORDER])
    write_json(root/'positions.json',json.loads((prep/'positions.initial.private.json').read_text()))
    binding=identity(Path(sys.executable),worktree,root)
    sha=freeze(root,instrument,binding)
    verify_freeze(root,instrument,identity(Path(sys.executable),worktree,root))
    receipt=dict(protocol=CONTRACT,status='pending TL',freeze_sha256=sha,identity_sha256=binding['sha256'],
        source_sha256=digest(prep/'agent-input/input/original.html'),rubric_sha256=digest(prep/'rubric.private.json'),
        runtime_inventory_sha256=digest(prep/'runtime.private.json'),
        roots={k:hashlib.sha256(data[k]['path'].encode()).hexdigest() for k in ['custody','scratch','runtime']},
        lifecycle=data['policy'],approval={},measured_sessions=0,preflight_attempts=0,preflight_success=None,
        native_preflight=False,usage=None,money=None)
    public_document(receipt)
    jsonschema.validate(receipt,json.loads((worktree/'docs/experiments/ipede-rebuild-v6-r2-tmp-v1.freeze.schema.json').read_text()))
    write_json(worktree/'docs/experiments/ipede-rebuild-v6-r2-tmp-v1.freeze.json',receipt)
    write_json(root/'seal.private.json',dict(freeze_sha256=sha,identity_sha256=binding['sha256'],status='pending TL',inventory=data))
    manifest(root)


if __name__=='__main__': main()
