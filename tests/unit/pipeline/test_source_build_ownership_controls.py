"""Normal entrypoint property mutation, publication failure and custody controls."""
from pathlib import Path

import pytest

from tests.unit.pipeline.test_binding_cli import build, pytestmark as pytestmark
from tests.unit.pipeline.test_binding_cli_controls import html_source, open_db


def load(db, connection):
    from design_graph.model.graph.reader import GraphReader
    from design_graph.model.graph.source_build_ownership import load_source_build_ownership
    return load_source_build_ownership(GraphReader(connection, Path(str(db) + '.state.json')))


@pytest.mark.parametrize('mutation', [
    "MATCH (s:Screen) SET s.source_code='<main>stale</main>'",
    "CREATE (:Screen {name:'foreign-screen'})",
    "MATCH (s:Section) SET s.source_code='<main>changed unselected section</main>'",
    "MATCH (m:Model) SET m.capture='foreign'",
    "MATCH (m:Model) DELETE m",
    "DROP TABLE NAVIGATES_TO",
    "ALTER TABLE Screen ADD foreign_field STRING",
])
def test_current_full_properties_checked_before_noop_skip(tmp_path, mutation):
    source = html_source(tmp_path)
    db = tmp_path / 'owned.db'
    built = build(source, db)
    assert built.returncode == 0, built.stderr
    database, connection = open_db(db)
    try:
        assert load(db, connection)
        connection.execute(mutation).close()
        with pytest.raises((ValueError, RuntimeError)):
            load(db, connection)
    finally:
        connection.close()
        database.close()
    result = build(source, db)
    assert result.returncode != 0 and 'skipped' not in result.stdout


@pytest.mark.parametrize('boundary', ['capture', 'general', 'receipt', 'private', 'link', 'state', 'seal'])
def test_normal_failure_matrix_never_exposed_usable_orphan(tmp_path, boundary):
    source = html_source(tmp_path)
    db = tmp_path / 'failed.db'
    faults = {
        'capture': "from design_graph.capture.binding_capture import BindingCapture\nBindingCapture.capture_source_syntax=lambda *a, **k: (_ for _ in ()).throw(ValueError('injected capture'))\n",
        'general': "from design_graph.model.graph.writer import GraphWriter\nGraphWriter.commit=lambda *a, **k: (_ for _ in ()).throw(ValueError('injected general'))\n",
        'receipt': "import design_graph.pipeline.binding_build as b\nb.append_receipt=lambda *a, **k: (_ for _ in ()).throw(ValueError('injected receipt'))\n",
        'private': "from design_graph.pipeline.binding_build import BindingWriteSession\nBindingWriteSession.verify_private=lambda *a, **k: (_ for _ in ()).throw(ValueError('injected private'))\n",
        'link': "import os\noriginal_link=os.link\ndef failed_link(a,b,*args,**kw):\n if str(b).endswith('failed.db'): raise OSError('injected link')\n return original_link(a,b,*args,**kw)\nos.link=failed_link\n",
        'state': "import design_graph.pipeline.coordinator as c\nc.save_build_state=lambda *a, **k: (_ for _ in ()).throw(ValueError('injected state'))\n",
        'seal': "from design_graph.pipeline.binding_build import BindingStage\nBindingStage.seal=lambda *a, **k: (_ for _ in ()).throw(ValueError('injected seal'))\n",
    }
    result = build(source, db, before=faults[boundary])
    assert result.returncode != 0 and ('injected ' + boundary) in result.stderr
    assert not Path(str(db) + '.binding.json').exists()
    if db.exists():
        database, connection = open_db(db)
        try:
            with pytest.raises((ValueError, FileNotFoundError)):
                load(db, connection)
        finally:
            connection.close()
            database.close()
    else:
        assert boundary not in ('state', 'seal')


def test_promotion_collision_preserved_existing_destination(tmp_path):
    source = html_source(tmp_path)
    db = tmp_path / 'collision.db'
    before = """
import os
original_link=os.link
def collide(a,b,*args,**kw):
 if str(b).endswith('collision.db'):
  from pathlib import Path
  Path(b).write_bytes(b'protected destination created during private validation')
 return original_link(a,b,*args,**kw)
os.link=collide
"""
    result = build(source, db, before=before)
    assert result.returncode != 0
    assert db.read_bytes() == b'protected destination created during private validation'
    assert not Path(str(db) + '.binding.json').exists()


def test_missing_retained_anchor_cannot_be_replaced_by_in_db_flag(tmp_path):
    source = html_source(tmp_path)
    db = tmp_path / 'owned.db'
    assert build(source, db).returncode == 0
    Path(str(db) + '.binding.json').unlink()
    database, connection = open_db(db)
    try:
        with pytest.raises(FileNotFoundError):
            load(db, connection)
    finally:
        connection.close()
        database.close()


def test_cross_document_shared_fragment_did_not_grant_inventory_ownership(tmp_path):
    source = html_source(tmp_path)
    db, other = tmp_path / 'first.db', tmp_path / 'second.db'
    assert build(source, db).returncode == 0
    # Exact same document/function fragment, different selected build domain.
    assert build(source, other).returncode == 0
    Path(str(db)+'.binding.json').write_bytes(Path(str(other)+'.binding.json').read_bytes())
    database, connection = open_db(db)
    try:
        with pytest.raises(ValueError, match='selected document/Screen'):
            load(db, connection)
    finally:
        connection.close()
        database.close()


def test_receipt_create_collision_rolled_back_exactly(tmp_path):
    from design_graph.model.graph.source_build_ownership import append_receipt
    source = html_source(tmp_path)
    db = tmp_path / 'owned.db'
    assert build(source, db).returncode == 0
    database, connection = open_db(db)
    try:
        value = load(db, connection)
        before = connection.execute('MATCH (s:BindingContextSnapshot) RETURN s.snapshot_id,s.payload ORDER BY s.snapshot_id').get_all()
        with pytest.raises(RuntimeError):
            append_receipt(connection, value)
        after = connection.execute('MATCH (s:BindingContextSnapshot) RETURN s.snapshot_id,s.payload ORDER BY s.snapshot_id').get_all()
        assert after == before
        assert load(db, connection) == value
    finally:
        connection.close()
        database.close()
