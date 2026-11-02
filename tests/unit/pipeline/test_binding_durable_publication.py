"""Publication must not rely on Kuzu's best-effort destructor checkpoint."""
import json
from pathlib import Path

import pytest

from tests.unit.pipeline.test_binding_cli import build, cli, pytestmark as pytestmark
from tests.unit.pipeline.test_binding_cli_controls import html_source


def test_checkpoint_failure_refused_publication(tmp_path):
    source = html_source(tmp_path)
    db = tmp_path / 'checkpoint-failed.db'
    before = """
import kuzu
execute = kuzu.Connection.execute
def fail_checkpoint(self, query, *args, **kwargs):
 if query.strip().upper() == 'CHECKPOINT':
  raise RuntimeError('injected checkpoint failure')
 return execute(self, query, *args, **kwargs)
kuzu.Connection.execute = fail_checkpoint
"""
    result = build(source, db, before=before)
    assert result.returncode != 0 and 'injected checkpoint failure' in result.stderr
    assert not db.exists()
    assert not Path(str(db) + '.binding.json').exists()


def test_wal_independent_final_name_reopened_in_fresh_process(tmp_path):
    source = html_source(tmp_path)
    db = tmp_path / 'durable.db'
    # Simulate Kuzu's documented best-effort close not checkpointing. The
    # explicit command must supply durability, not a later destructor or WAL.
    before = """
import os, kuzu
from pathlib import Path
close = kuzu.Database.close
execute = kuzu.Connection.execute
checkpoints = set()
def track_checkpoint(self, query, *args, **kwargs):
 result = execute(self, query, *args, **kwargs)
 if query.strip().upper() == 'CHECKPOINT':
  checkpoints.add(str(self.database.database_path))
 return result
def close_without_checkpoint(self):
 path = str(self.database_path)
 if not self.read_only and '.building' in path and path not in checkpoints:
  # A crash after the WAL commit reproduces the original close behavior:
  # committed rows are recoverable by private-name readers, not by final name.
  os._exit(91)
 return close(self)
kuzu.Connection.execute = track_checkpoint
kuzu.Database.close = close_without_checkpoint
"""
    result = build(source, db, before=before)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['status'] == 'built'
    assert not list(tmp_path.glob('*.building.wal'))
    read = cli('design_graph.interface.cli.query', ['binding-context', '--db', db,
        '--snapshot', json.loads(Path(str(db)+'.binding.json').read_text())['snapshot'],
        '--unit', json.loads(Path(str(db)+'.binding.json').read_text())['roots'][0]['unit'],
        '--region', json.loads(Path(str(db)+'.binding.json').read_text())['roots'][0]['region']], cold=True)
    assert read.returncode == 0, read.stderr
    reuse = build(source, db)
    assert reuse.returncode == 0 and json.loads(reuse.stdout)['status'] == 'skipped', reuse.stderr


@pytest.mark.parametrize('fault', ['missing', 'digest', 'unexpected-wal', 'general'])
def test_final_name_readback_refused_changed_artifact_before_seal(tmp_path, fault):
    source = html_source(tmp_path)
    db = tmp_path / 'changed.db'
    before = """
import os, kuzu
from pathlib import Path
link = os.link
def change_after_link(a, b, *args, **kwargs):
 result = link(a, b, *args, **kwargs)
 if str(b).endswith('changed.db'):
  fault = FAULT
  if fault == 'unexpected-wal':
   Path(str(b)+'.wal').touch()
  else:
   database = kuzu.Database(str(b), buffer_pool_size=128*1024*1024, max_num_threads=2)
   connection = kuzu.Connection(database)
   try:
    if fault == 'general':
     statement = "MATCH (s:Screen) SET s.source_code='changed graph with intact receipt'"
    else:
     statement = "MATCH (s:BindingContextSnapshot) WHERE contains(s.payload, 'source-build-ownership/3') "
     statement += 'DELETE s' if fault == 'missing' else "SET s.payload='changed'"
    connection.execute(statement).close()
    connection.execute('CHECKPOINT').close()
   finally:
    connection.close(); database.close()
 return result
os.link = change_after_link
""".replace('FAULT', repr(fault))
    result = build(source, db, before=before)
    assert result.returncode != 0, result.stdout
    assert 'published' in result.stderr, result.stderr
    assert db.exists()  # a diagnostic orphan, not a completed artifact
    assert not Path(str(db) + '.state.json').exists()
    assert not Path(str(db) + '.binding.json').exists()


@pytest.mark.parametrize('boundary', ['main', 'directory'])
def test_fsync_failure_never_published_completion(tmp_path, boundary):
    source = html_source(tmp_path)
    db = tmp_path / 'fsync.db'
    before = """
import os, stat
fsync = os.fsync
def fail_fsync(fd):
 mode = os.fstat(fd).st_mode
 path = os.readlink('/proc/self/fd/' + str(fd))
 if (BOUNDARY == 'directory' and stat.S_ISDIR(mode)) or (BOUNDARY == 'main' and path.endswith('.building')):
  raise OSError('injected fsync failure')
 return fsync(fd)
os.fsync = fail_fsync
""".replace('BOUNDARY', repr(boundary))
    result = build(source, db, before=before)
    assert result.returncode != 0 and 'injected fsync failure' in result.stderr
    assert db.exists() == (boundary == 'directory')
    assert not Path(str(db) + '.state.json').exists()
    assert not Path(str(db) + '.binding.json').exists()
