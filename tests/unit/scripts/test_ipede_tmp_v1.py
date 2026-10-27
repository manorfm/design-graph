"""Synthetic lifecycle regressions. Never collect or launch a real executor."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import pytest
from scripts.ipede_rebuild_v6 import lifecycle as lc
from scripts.ipede_rebuild_v6.common import environment, write_json
from scripts.ipede_rebuild_v6.audit import trace_gate


@pytest.fixture
def round_root(tmp_path,monkeypatch):
    # Positive retirement tests control the process table; real child covered below.
    monkeypatch.setattr(lc,"process_entries",lambda:[])
    # Durable synthetic custody is under the caller's explicit --basetemp scratch.
    root=tmp_path/'custody'; root.mkdir(mode=0o700)
    (root/'preparation').mkdir(mode=0o700)
    scratch=tmp_path/'scratch'; scratch.mkdir(mode=0o700)
    data=lc.allocate(root,scratch)
    write_json(root/'freeze.json',{'files':{lc.INVENTORY:lc.digest(root/'preparation'/lc.INVENTORY)}})
    yield root,data
    runtime=Path(data['runtime']['path'])
    # Test-only cleanup of this exact fresh allocation; never experiment collection.
    shutil.rmtree(runtime)


def test_inventory_physical_local_subprocesses(round_root):
    root,data=round_root
    assert len(data['workspaces']) == 7
    assert Path(data['runtime']['path']).parent == Path('/tmp')
    dirs=[]
    for key in data['workspaces']:
        work=lc.workspace(root,key); env=environment(work); dirs.append(env['TMPDIR'])
        code='import os,tempfile; p=tempfile.NamedTemporaryFile(); print(p.name)'
        proc=subprocess.run([sys.executable,'-c',code],env=env,cwd=work,text=True,capture_output=True,check=True)
        assert Path(proc.stdout.strip()).is_relative_to(work/'tmp')
        assert all(Path(env[k]).is_relative_to(work) for k in ['TMPDIR','XDG_CACHE_HOME','XDG_RUNTIME_DIR','PIP_CACHE_DIR'])
        assert all(lc.owned(Path(item['path'])) == item for item in data['directories'])
    assert len(set(dirs)) == 7


def test_symlink_mode_and_owner_rejected(round_root,monkeypatch):
    root,data=round_root; work=lc.workspace(root,'1-A')
    work.chmod(0o755)
    with pytest.raises(ValueError,match='ownership/mode'): lc.validate(root)
    work.chmod(0o700)
    cache=work/'cache'; cache.rmdir(); cache.symlink_to(work/'tmp',target_is_directory=True)
    with pytest.raises(ValueError,match='symlink'): environment(work)
    cache.unlink(); cache.mkdir(mode=0o700)
    monkeypatch.setattr(lc.os,'getuid',lambda:-1)
    with pytest.raises(ValueError,match='ownership'): lc.owned(work)


def test_outside_inventory_and_inode_rejected(round_root):
    root,data=round_root; path=root/'preparation'/lc.INVENTORY
    changed=json.loads(path.read_text());changed['workspaces']['1-A']=str(root)
    write_json(path,changed)
    with pytest.raises(ValueError,match='workspace inventory'):lc.validate(root)
    write_json(path,data)
    work=lc.workspace(root,'1-A'); moved=work.with_name('saved');work.rename(moved);work.mkdir(mode=0o700)
    with pytest.raises(ValueError):lc.validate(root)


def test_cleanup_preserves_every_byte_and_only_pf(round_root):
    root,data=round_root; work=lc.workspace(root,'preflight')
    (work/'state/log').write_bytes(b'neutral failure literal\x00')
    (work/'link').symlink_to('state/log')
    before=lc.snapshot(Path(data['preflight']))
    folder=root/'preflight-v6-r2';folder.mkdir(mode=0o700);(folder/'evidence').mkdir(mode=0o700)
    (folder/'evidence/raw.log').write_text('neutral durable')
    lc.retire_preflight(root)
    assert lc.snapshot(folder/'runtime-preserved') == before
    assert not Path(data['preflight']).exists()
    assert lc.validate(root)
    assert Path(data['collection']).is_dir()
    assert (folder/'evidence/raw.log').read_text() == 'neutral durable'
    receipt=json.loads((folder/'cleanup.private.json').read_text()); assert receipt['absent']
    assert receipt['retained_reason']


def test_preservation_mismatch_retains_original(round_root,monkeypatch):
    root,data=round_root;folder=root/'preflight-v6-r2';folder.mkdir(mode=0o700)
    work=lc.workspace(root,'preflight');(work/'literal').write_text('neutral')
    real=lc.shutil.copytree
    def corrupt(*args,**kwargs):
        out=real(*args,**kwargs)
        if Path(out).name == 'runtime-preserved': (Path(out)/'w/literal').write_text('mismatch')
        return out
    monkeypatch.setattr(lc.shutil,'copytree',corrupt)
    with pytest.raises(ValueError,match='preservation mismatch'):lc.retire_preflight(root)
    assert (work/'literal').read_text() == 'neutral'
    assert not (folder/'cleanup.private.json').exists()


def test_live_process_blocks_cleanup(round_root,monkeypatch):
    root,data=round_root;folder=root/'preflight-v6-r2';folder.mkdir(mode=0o700)
    work=lc.workspace(root,'preflight')
    proc=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],cwd=work,env=environment(work))
    monkeypatch.setattr(lc,'process_entries',lambda:[Path('/proc')/str(proc.pid)])
    try:
        with pytest.raises(ValueError,match='live process'):lc.retire_preflight(root)
        assert work.exists()
        assert (folder/'preservation.private.json').exists()
    finally:proc.terminate();proc.wait(timeout=5)


def test_trace_exact_workspace_boundary(round_root):
    root,data=round_root;work=lc.workspace(root,'1-A')
    def events(cmd):return [{'type':'item.completed','item':{'type':'command_execution','command':cmd}}]
    assert trace_gate(events(f'cat {work}/input/original.html'),'A',work)
    for path in ['/tmp/global',str(work)+'-sibling/private',str(work.parent),str(work/'../1B/private')]:
        with pytest.raises(ValueError):trace_gate(events('cat '+path),'A',work)
    with pytest.raises(ValueError):trace_gate(events('rm -rf output'),'A',work)


def test_inaccessible_process_blocks_removal_after_preservation(round_root,monkeypatch):
    root,data=round_root;folder=root/'preflight-v6-r2';folder.mkdir(mode=0o700)
    class Unknown:
        name='12345'
        def stat(self): raise PermissionError('synthetic inaccessible process')
    monkeypatch.setattr(lc,'process_entries',lambda:[Unknown()])
    with pytest.raises(ValueError,match='cannot establish idle'):lc.retire_preflight(root)
    assert Path(data['preflight']).exists()
    assert (folder/'preservation.private.json').exists()
    assert not (folder/'cleanup.private.json').exists()


def test_incomplete_inventory_and_preserved_tampering(round_root):
    root,data=round_root;path=root/'preparation'/lc.INVENTORY
    changed=json.loads(path.read_text());changed['directories'].pop()
    write_json(path,changed)
    with pytest.raises(ValueError,match='incomplete directory'):lc.validate(root)
    write_json(path,data)
    folder=root/'preflight-v6-r2';folder.mkdir(mode=0o700)
    work=lc.workspace(root,'preflight');(work/'literal').write_text('neutral')
    lc.retire_preflight(root)
    (folder/'runtime-preserved/w/literal').write_text('changed')
    with pytest.raises(ValueError,match='durable preservation changed'):lc.validate(root)


def test_preflight_abort_preserves_gate_and_runtime_without_retry(round_root,monkeypatch):
    from scripts.ipede_rebuild_v6 import preflight as pf, gates
    root,data=round_root
    binding={'synthetic':True}
    monkeypatch.setattr(pf,'identity',lambda *a,**k:binding)
    (root/'freeze.json').unlink()
    gates.freeze(root,Path(pf.__file__).parent,binding)
    launches=[]
    def fail(*args,**kwargs):
        launches.append(args)
        raise RuntimeError('synthetic neutral launch failure literal')
    monkeypatch.setattr(pf.subprocess,'Popen',fail)
    with pytest.raises(RuntimeError,match='failure literal'):
        pf.preflight(root,Path(sys.executable),Path.cwd())
    folder=root/'preflight-v6-r2'
    gate=json.loads((folder/'gate.json').read_text())
    assert gate['success'] is False and gate['diagnostic'] == 'synthetic neutral launch failure literal'
    assert (folder/'cleanup.private.json').exists()
    assert (folder/'runtime-preserved/w/neutral.html').read_text() == pf.FIXTURE
    assert json.loads((root/'TL-approval.json').read_text()) == {}
    with pytest.raises(ValueError):pf.preflight(root,Path(sys.executable),Path.cwd())
    assert len(launches) == 1


def test_trace_symlink_escape_rejected(round_root):
    root,data=round_root;work=lc.workspace(root,'1-A')
    (work/'outside').symlink_to(root,target_is_directory=True)
    events=[{'item':{'type':'command_execution','command':f'cat {work}/outside/private'}}]
    with pytest.raises(ValueError,match='symlink/outside'):trace_gate(events,'A',work)


def test_changed_frozen_inventory_never_cleans(round_root):
    root,data=round_root;folder=root/'preflight-v6-r2';folder.mkdir(mode=0o700)
    changed=dict(data);changed['policy']=dict(data['policy'],preflight='tampered')
    write_json(root/'preparation'/lc.INVENTORY,changed)
    with pytest.raises(ValueError,match='frozen inventory'):lc.retire_preflight(root)
    assert Path(data['preflight']).exists()
    assert not (folder/'runtime-preserved').exists()


def test_session_preservation_never_deletes_runtime(round_root):
    root,data=round_root;work=lc.workspace(root,'1-A')
    (work/'output').mkdir(mode=0o700);(work/'output/page.html').write_text('neutral partial failure')
    sessions=root/'sessions';sessions.mkdir(mode=0o700)
    session=sessions/'1-A';session.mkdir(mode=0o700)
    lc.preserve_work(root,'1-A',session)
    assert work.is_dir() and Path(data['collection']).is_dir()
    assert lc.snapshot(work) == lc.snapshot(session/'work')
    assert json.loads((session/'preservation.private.json').read_text())['verified']
    with pytest.raises(ValueError,match='outside durable'):lc.preserve_work(root,'1-A',root)


def test_manifest_never_reads_symlink_target(round_root,monkeypatch):
    from scripts.ipede_rebuild_v6 import common
    root,_=round_root
    link=root/'external-link';link.symlink_to('/outside/nonexistent-private')
    before=common.hashes(root)
    assert 'external-link' in before
    link.unlink();link.symlink_to('/different/nonexistent-private')
    assert common.hashes(root)['external-link'] != before['external-link']
