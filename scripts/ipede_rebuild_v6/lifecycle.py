"""Physical tmp-v1 allocation and fail-closed, verified preflight retirement.

Collection is retained, never cleaned here. This is not a security sandbox.
"""
from __future__ import annotations
import fcntl
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
from .common import environment, fresh, write_json, digest
from .protocol import ORDER

CONTRACT = 'ipede-rebuild-v6-r2-tmp-v1'
INVENTORY = 'runtime.private.json'


def physical(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('absolute physical path required')
    for part in [*reversed(path.parents), path]:
        if part.is_symlink():
            raise ValueError('symlink/alias forbidden')
    if path.resolve() != path:
        raise ValueError('physical spelling required')
    return path


def owned(path):
    path = physical(path)
    s = path.stat()
    if not stat.S_ISDIR(s.st_mode) or s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) != 0o700:
        raise ValueError('directory ownership/mode must be current uid/0700')
    return dict(path=str(path), uid=s.st_uid, mode=stat.S_IMODE(s.st_mode), dev=s.st_dev, ino=s.st_ino)


def allocate(root, scratch):
    root = physical(root); scratch = physical(scratch)
    owned(root); owned(scratch)
    if root.is_relative_to('/tmp') or scratch.is_relative_to('/tmp'):
        raise ValueError('durable custody/scratch must be outside /tmp')
    if root == scratch or root in scratch.parents or scratch in root.parents:
        raise ValueError('disjoint custody and scratch required')
    target = root/'preparation'/INVENTORY
    if target.exists(): raise ValueError('inventory exists; no reallocation')
    runtime = Path(tempfile.mkdtemp(dir='/tmp', prefix='r2-'))
    preflight = fresh(runtime/'pf')
    collection = fresh(runtime/'c')
    works = {'preflight':fresh(preflight/'w')}
    for page, lane in ORDER:
        works[f'{page}-{lane}'] = fresh(collection/f'{page}{lane}')
    dirs = [runtime, preflight, collection]
    for work in works.values():
        environment(work)
        dirs += [work, *[p for p in work.iterdir() if p.is_dir()]]
    data = dict(contract=CONTRACT, custody=owned(root), scratch=owned(scratch), runtime=owned(runtime),
                preflight=str(preflight), collection=str(collection),
                workspaces={k:str(v) for k,v in works.items()}, directories=[owned(p) for p in dirs],
                policy=dict(preflight='copy complete work to durable; verify hashes; check no live users; remove only inventoried pf subtree; readback absence',
                            collection='no cleanup during collection', retained_reason='six downstream sessions after exact TL approval; integral index retained in scratch'))
    write_json(target, data)
    return validate(root)


def validate(root, *, allow_retired=True):
    root = physical(root); owned(root)
    data = json.loads((root/'preparation'/INVENTORY).read_text())
    if data['contract'] != CONTRACT or data['custody'] != owned(root):
        raise ValueError('custody/contract binding mismatch')
    runtime = physical(data['runtime']['path'])
    if runtime.parent != Path('/tmp') or not runtime.name.startswith('r2-'):
        raise ValueError('outside allocated /tmp root')
    if data['runtime'] != owned(runtime) or data['scratch'] != owned(data['scratch']['path']):
        raise ValueError('runtime/scratch identity mismatch')
    if data['preflight'] != str(runtime/'pf') or data['collection'] != str(runtime/'c'):
        raise ValueError('outside inventory roots')
    expected = {'preflight':str(runtime/'pf/w'), **{f'{p}-{l}':str(runtime/f'c/{p}{l}') for p,l in ORDER}}
    if data['workspaces'] != expected: raise ValueError('workspace inventory mismatch')
    retired = root/'preflight-v6-r2/cleanup.private.json'
    receipt = json.loads(retired.read_text()) if allow_retired and retired.is_file() else None
    local_dirs=['tmp','cache','config','data','state','runtime','npm','pip','uv','mpl','pycache','cuda']
    expected_dirs={runtime,runtime/'pf',runtime/'c'}
    for work in expected.values():
        expected_dirs.add(Path(work))
        expected_dirs.update(Path(work)/name for name in local_dirs)
    if len(data['directories']) != len(expected_dirs) or {Path(i['path']) for i in data['directories']} != expected_dirs:
        raise ValueError('incomplete directory inventory')
    if receipt:
        preservation=root/'preflight-v6-r2/preservation.private.json'
        if (receipt.get('contract') != CONTRACT or receipt.get('removed') != str(runtime/'pf')
            or receipt.get('absent') is not True or receipt.get('preservation_sha256') != digest(preservation)):
            raise ValueError('retirement receipt mismatch')
        saved=json.loads(preservation.read_text())
        if saved.get('source') != str(runtime/'pf') or saved.get('verified') is not True or snapshot(root/'preflight-v6-r2/runtime-preserved') != saved['files']:
            raise ValueError('durable preservation changed')
    for item in data['directories']:
        path = physical(item['path'])
        if not path.is_relative_to(runtime): raise ValueError('outside inventory root')
        if receipt and path.is_relative_to(runtime/'pf'):
            if path.exists() or path.is_symlink(): raise ValueError('retired preflight reappeared')
        elif owned(path) != item: raise ValueError('directory inventory changed')
    return data


def workspace(root, key):
    data = validate(root)
    path = Path(data['workspaces'][key])
    if not path.exists(): raise ValueError('workspace already retired')
    return path


def snapshot(root):
    """Hash every file and retain symlink bytes without following them."""
    records = {}
    for base, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            p = Path(base)/name; s = p.lstat(); rel = str(p.relative_to(root))
            if s.st_uid != os.getuid(): raise ValueError('foreign ownership in runtime')
            record = dict(mode=stat.S_IMODE(s.st_mode), uid=s.st_uid)
            if p.is_symlink(): record.update(kind='symlink', target=os.readlink(p))
            elif p.is_dir(): record.update(kind='directory')
            elif p.is_file(): record.update(kind='file', sha256=digest(p), size=s.st_size)
            else: raise ValueError('special/live file cannot be preserved')
            records[rel] = record
    return records


def process_entries():
    return list(Path('/proc').iterdir())


def assert_idle(target):
    """Linux best-effort live-user check; inaccessible same-uid entries block."""
    target = str(physical(target))
    def inside(value): return value == target or value.startswith(target+'/')
    for proc in process_entries():
        if not proc.name.isdigit(): continue
        try:
            if proc.stat().st_uid != os.getuid(): continue
            if not os.access(proc/'cwd', os.F_OK) or not os.access(proc/'fd', os.R_OK | os.X_OK):
                raise ValueError(f'cannot establish idle runtime: pid={proc.name}; retained')
            links = [proc/'cwd', proc/'root', *list((proc/'fd').iterdir())]
            for link in links:
                try: value = os.readlink(link).removesuffix(' (deleted)')
                except FileNotFoundError: continue
                if inside(value): raise ValueError('live process references cleanup target')
            args = (proc/'cmdline').read_bytes().split(b'\0')
            if any(inside(a.decode(errors='replace').split('=',1)[-1]) for a in args):
                raise ValueError('live process arguments reference cleanup target')
            for mapping in (proc/'maps').read_text().splitlines():
                fields=mapping.split(maxsplit=5)
                if len(fields)==6 and inside(fields[5].removesuffix(' (deleted)')):
                    raise ValueError('live process mapping references cleanup target')
        except (FileNotFoundError, ProcessLookupError): continue
        except PermissionError as exc: raise ValueError(f'cannot establish idle runtime: pid={proc.name}; retained') from exc


def preserve_work(root, key, session):
    """Durable session copy on success/failure, with no runtime deletion."""
    work=workspace(root,key)
    session=physical(session)
    if session != root/'sessions'/key: raise ValueError('outside durable session')
    owned(session)
    before=snapshot(work)
    archive=session/'work'
    shutil.copytree(work,archive,symlinks=True)
    if snapshot(archive) != before or snapshot(work) != before:
        raise ValueError('session preservation mismatch; runtime retained')
    write_json(session/'preservation.private.json',dict(contract=CONTRACT,source=str(work),files=before,
        verified=True,retained_reason='no cleanup during collection; runtime retained'))


def retire_preflight(root, freeze_sha256=None):
    """Never accept arbitrary deletion paths. Failure leaves runtime intact."""
    data = validate(root, allow_retired=False)
    frozen=json.loads((root/'freeze.json').read_text())
    if (frozen['files'].get(INVENTORY) != digest(root/'preparation'/INVENTORY)
        or (freeze_sha256 is not None and digest(root/'freeze.json') != freeze_sha256)):
        raise ValueError('frozen inventory changed; no cleanup')
    target = Path(data['preflight']); folder = root/'preflight-v6-r2'
    owned(folder)
    with (folder/'cleanup.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (folder/'cleanup.private.json').exists(): raise ValueError('cleanup already attempted')
        before = snapshot(target)
        archive = folder/'runtime-preserved'
        shutil.copytree(target, archive, symlinks=True)
        if snapshot(archive) != before or snapshot(target) != before:
            raise ValueError('preservation mismatch; runtime retained')
        write_json(folder/'preservation.private.json', dict(source=str(target), files=before, verified=True))
        # Re-read the durable bytes and live state immediately before deletion.
        if snapshot(archive) != before: raise ValueError('durable preservation mismatch')
        validate(root, allow_retired=False); assert_idle(target)
        if snapshot(target) != before: raise ValueError('runtime changed before cleanup')
        shutil.rmtree(target)
        if target.exists() or target.is_symlink(): raise ValueError('cleanup absence readback failed')
        write_json(folder/'cleanup.private.json', dict(contract=CONTRACT, removed=str(target), absent=True,
            preservation_sha256=digest(folder/'preservation.private.json'), retained=str(data['collection']),
            retained_reason=data['policy']['retained_reason']))
