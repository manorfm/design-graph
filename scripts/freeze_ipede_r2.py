"""Seal blocked R2 preparation without launching preflight or collection."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import re
import subprocess
import jsonschema

from scripts.ipede_rebuild_v6.common import CONTRACT, digest, write_json
from scripts.ipede_rebuild_v6.failures import POLICY
from scripts.ipede_rebuild_v6.gates import freeze, manifest, public_document, socket_precheck
from scripts.ipede_rebuild_v6.preflight import identity
from scripts.ipede_rebuild_v6.protocol import ORDER
from scripts.ipede_rebuild_v6.rubric import verify_references


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--scratch',type=Path,required=True)
    args=parser.parse_args();root=args.root.resolve();scratch=args.scratch.resolve();worktree=Path.cwd()
    instrument=worktree/'scripts/ipede_rebuild_v6';prep=root/'preparation'
    verify_references(prep,json.loads((prep/'rubric.private.json').read_text()))
    tmpdir=root/'preflight-v6-r2/work/tmp'
    try:socket_precheck(tmpdir)
    except ValueError as exc:
        block=dict(status='blocked',diagnostic=str(exc),tmpdir=str(tmpdir),
                   socket_path_bytes=len((str(tmpdir.resolve())+'/codex-stdio-xxxxxxxxxxxx.sock').encode()),limit=107,
                   preflight_launched=False,success=False)
    else:raise ValueError('This sealer only handles blocked paths; do not infer preflight success')
    write_json(root/'socket-block.private.json',block)
    write_json(root/'positions.json',[dict(page=p,lane=l,status='not_started',reason='socket_precheck_blocked',
        artifact=None,accepted=None) for p,l in ORDER])
    write_json(prep/'failure-policy.private.json',POLICY)
    logs=['install.log','preparation.log','focal-sealed.log','pytest-sealed.log','make-build.log','diff-check.log']
    for name in logs:
        if not (scratch/name).is_file():raise ValueError('missing validation log: '+name)
    for name in ['focal-sealed.log','pytest-sealed.log']:
        if not re.search(r'(?m)^\d+ passed(?:, \d+ skipped)?(?:, \d+ warning)? in ', (scratch/name).read_text()):
            raise ValueError('no passing terminal pytest summary: '+name)
    write_json(prep/'workspace.private.json',dict(worktree=str(worktree),scratch=str(scratch),custody=str(root),
        python=str(Path(sys.executable)),
        git_head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        git_branch=subprocess.check_output(['git','branch','--show-current'],text=True).strip()))
    write_json(prep/'validation.private.json',dict(scratch=str(scratch),logs={name:digest(scratch/name) for name in logs},
        tests=digest(worktree/'tests/unit/scripts/test_ipede_rebuild_v6.py'),
        preparation_script=digest(worktree/'scripts/prepare_ipede_r2.py'),sealing_script=digest(Path(__file__))))
    binding=identity(Path(sys.executable),worktree,root)
    sha=freeze(root,instrument,binding)
    receipt=dict(protocol=CONTRACT,status='blocked',freeze_sha256=sha,identity_sha256=binding['sha256'],
        source_sha256=digest(prep/'agent-input/input/original.html'),rubric_sha256=digest(prep/'rubric.private.json'),
        schema_sha256=digest(instrument/'data.schema.json'),tests_sha256=digest(worktree/'tests/unit/scripts/test_ipede_rebuild_v6.py'),
        failure_policy_sha256=digest(prep/'failure-policy.private.json'),
        worktree_sha256=hashlib.sha256(str(worktree).encode()).hexdigest(),
        venv_sha256=hashlib.sha256(str(Path(sys.executable).parent.parent).encode()).hexdigest(),
        oracle_real=True,integral_index_ready=json.loads((prep/'readiness.private.json').read_text())['ready'],
        native_preflight=False,preflight_attempts=0,preflight_usage=None,approval='pending',measured_sessions=0,money=None,
        socket=dict(path_bytes=block['socket_path_bytes'],limit=107),publication='blocked: Telegram text result and subsequent acceptance required')
    public_document(receipt)
    jsonschema.validate(receipt,json.loads((worktree/'docs/experiments/ipede-rebuild-v6-r2.freeze.schema.json').read_text()))
    write_json(worktree/'docs/experiments/ipede-rebuild-v6-r2.freeze.json',receipt)
    print(json.dumps(dict(freeze_sha256=sha,manifest_sha256=manifest(root)),indent=2))


if __name__=='__main__':main()
