from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path

CONTRACT = 'ipede-rebuild-v6-r2-tmp-v1'

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

def fresh(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=False, mode=0o700)
    return path

def environment(root):
    root = Path(root)
    from .lifecycle import owned
    owned(root)
    # Keep the real spelling. Never shorten TMPDIR to evade a socket guard.
    env = dict(os.environ)
    for key, name in {'TMPDIR':'tmp', 'TMP':'tmp', 'TEMP':'tmp',
                      'XDG_CACHE_HOME':'cache', 'XDG_CONFIG_HOME':'config',
                      'XDG_DATA_HOME':'data', 'XDG_STATE_HOME':'state'}.items():
        path = root/name
        path.mkdir(exist_ok=True, mode=0o700)
        owned(path)
        env[key] = str(path)
    for key, name in {'XDG_RUNTIME_DIR':'runtime', 'NPM_CONFIG_CACHE':'npm',
                      'PIP_CACHE_DIR':'pip', 'UV_CACHE_DIR':'uv', 'MPLCONFIGDIR':'mpl',
                      'PYTHONPYCACHEPREFIX':'pycache', 'SQLITE_TMPDIR':'tmp',
                      'CUDA_CACHE_PATH':'cuda', 'NODE_REPL_HISTORY':'node-history'}.items():
        path = root/name
        if key != 'NODE_REPL_HISTORY': path.mkdir(exist_ok=True, mode=0o700)
        if key != 'NODE_REPL_HISTORY': owned(path)
        elif path.is_symlink(): raise ValueError('symlink history forbidden')
        env[key] = str(path)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    return env

def hashes(root):
    # Preserve link bytes without reading any target outside the custody tree.
    return {p.relative_to(root).as_posix():
            hashlib.sha256(b'symlink\0'+os.fsencode(os.readlink(p))).hexdigest() if p.is_symlink() else digest(p)
            for p in sorted(Path(root).rglob('*')) if p.is_symlink() or p.is_file()}
