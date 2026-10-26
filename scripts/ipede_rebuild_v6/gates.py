"""Fail-closed approval, immutable freeze and private/public boundaries."""
import hashlib
import json
import re
from pathlib import Path
from .common import digest, hashes, write_json


def socket_precheck(tmpdir, limit=107, suffix='/codex-stdio-xxxxxxxxxxxx.sock'):
    # Linux sockaddr_un: 108 bytes including NUL. No probing with shorter paths.
    size = len((str(Path(tmpdir).resolve())+suffix).encode())
    result = {'tmpdir':str(tmpdir),'socket_path_bytes':size,'limit':limit,'passed':size<=limit}
    if size > limit:
        raise ValueError(f'TMPDIR socket precheck: {size} > {limit}; stop, no alias/shortening')
    return result


def disjoint(*roots):
    roots = [Path(p).resolve() for p in roots]
    if any(a == b or a in b.parents or b in a.parents
           for i,a in enumerate(roots) for b in roots[i+1:]):
        raise ValueError('oracle, input and session roots must be disjoint')


def safe_hashes(root):
    return {k:v for k,v in hashes(root).items() if '__pycache__' not in Path(k).parts
            and not k.endswith('.pyc')}


def freeze(root, instrument, identity):
    root = Path(root)
    if (root/'freeze.json').exists(): raise ValueError('freeze exists; do not replace it')
    files = safe_hashes(root/'preparation')
    payload = {'protocol':'ipede-rebuild-v6','files':files,
               'instrument':safe_hashes(instrument),'identity':identity,
               'collection_status':'pending TL review','approval_required':True}
    write_json(root/'freeze.json',payload)
    # Always pending: creating a freeze must never authorize collection.
    (root/'TL-approval.json').write_text('{}\n')
    return digest(root/'freeze.json')


def verify_freeze(root, instrument, identity):
    root = Path(root); data = json.loads((root/'freeze.json').read_text())
    if (data['files'] != safe_hashes(root/'preparation') or
        data['instrument'] != safe_hashes(instrument) or data['identity'] != identity):
        raise ValueError('freeze changed: preparation/instrument/environment')
    return data


def approval(root, instrument, identity):
    verify_freeze(root,instrument,identity)
    decision = json.loads((Path(root)/'TL-approval.json').read_text())
    if (decision.get('approved') is not True or decision.get('reviewer_role') != 'TL'
        or not decision.get('reviewer') or not decision.get('reviewed_at')
        or decision.get('freeze_sha256') != digest(Path(root)/'freeze.json')):
        raise ValueError('pending TL approval bound to exact freeze SHA256')


def public_document(value):
    text = json.dumps(value,ensure_ascii=False)
    if re.search(r'(?i)(/home/|file://|auth\.json|<script|data:image|selector|module_offset|application_offset|api[_-]?key|bearer\s)',text):
        raise ValueError('private data in public document')
    return value


def manifest(root):
    root = Path(root)
    files = {k:v for k,v in safe_hashes(root).items() if k != 'manifest.private.json'}
    write_json(root/'manifest.private.json',{'algorithm':'sha256','files':files})
    if files != {k:v for k,v in safe_hashes(root).items() if k != 'manifest.private.json'}:
        raise ValueError('durable evidence changed during manifest verification')
    return digest(root/'manifest.private.json')
