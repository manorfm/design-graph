from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path

CONTRACT = 'benchmark-ipede-v2'
ROUND = 'iPede-3pages-v3'
_TMP_FDS = []  # keep /proc/<observer>/fd aliases alive; physical writes stay in scratch

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

def fresh(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=False, mode=0o700)
    return path

def root_path(value):
    root = Path(value).resolve()
    if not root.is_dir() or root.stat().st_uid != os.getuid():
        raise ValueError('scratch must exist and belong to this user')
    return root

def environment(root):
    env = dict(os.environ)
    for key, name in {'TMPDIR':'tmp', 'TMP':'tmp', 'TEMP':'tmp', 'XDG_CACHE_HOME':'cache',
                      'XDG_CONFIG_HOME':'config', 'XDG_DATA_HOME':'data', 'XDG_STATE_HOME':'state',
                      'PYTHONPYCACHEPREFIX':'pycache', 'UV_CACHE_DIR':'cache'}.items():
        path = root/name
        path.mkdir(exist_ok=True)
        env[key] = str(path)
    # Chromium Unix socket names exceed 108 bytes under long scratch paths.
    # A proc-fd alias shortens only the spelling, without writing outside scratch.
    fd = os.open(root/'tmp', os.O_RDONLY | os.O_DIRECTORY)
    _TMP_FDS.append(fd)
    for key in ['TMPDIR', 'TMP', 'TEMP']:
        env[key] = f'/proc/{os.getpid()}/fd/{fd}'
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    return env

def hashes(root):
    return {p.relative_to(root).as_posix(): digest(p) for p in sorted(Path(root).rglob('*')) if p.is_file()}

def verify(preparation):
    receipt = json.loads((preparation/'freeze.json').read_text())
    for rel, expected in receipt['files'].items():
        if digest(preparation/rel) != expected:
            raise ValueError('frozen file changed: ' + rel)
    for rel, expected in receipt.get('instrument_hashes', {}).items():
        if digest(Path(__file__).parent/rel) != expected:
            raise ValueError('frozen instrument changed: ' + rel)
    return receipt
