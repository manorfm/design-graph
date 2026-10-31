"""Finite hostile receipt admission and retained producer inventory."""
import json
from dataclasses import replace
from pathlib import Path

import pytest

from tests.unit.pipeline.test_binding_cli import build, pytestmark as pytestmark
from tests.unit.pipeline.test_binding_cli_controls import html_source, open_db


@pytest.fixture(scope='module')
def owned(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp('ownership-admission')
    from design_graph.model.graph.reader import GraphReader
    from design_graph.model.graph.source_build_ownership import load_source_build_ownership
    source = html_source(tmp_path)
    source.write_text(source.read_text().replace('</body>', '<script>const SECOND=72;</script></body>'))
    db = tmp_path / 'owned.db'
    result = build(source, db)
    assert result.returncode == 0, result.stderr
    database, connection = open_db(db)
    try:
        reader = GraphReader(connection, Path(str(db) + '.state.json'))
        yield load_source_build_ownership(reader), reader, db
    finally:
        connection.close()
        database.close()


def test_changed_syntax_producer_cannot_relabel_inventory(owned):
    from design_graph.model.graph.source_syntax_context import SourceSyntaxSnapshot
    value, _, _ = owned
    captures = tuple(replace(c, producer_fingerprint='f'*64) for c in value.syntax.captures)
    syntax = SourceSyntaxSnapshot.create(value.syntax.scope, captures)
    changed = replace(value, syntax=syntax, syntax_sha256=syntax.digest())
    with pytest.raises(ValueError, match='producer'):
        changed.to_json()


@pytest.mark.parametrize('mutation', [
    lambda v: {**v, 'version': 'source-build-ownership/99'},
    lambda v: {**v, 'builder': 'binding-build/3'},
    lambda v: {**v, 'input_bytes': True},
    lambda v: {**v, 'input_sha256': 'not-a-hash'},
    lambda v: {**v, 'provenance': True},
    lambda v: {**v, 'domain': {**v['domain'], 'screens': []}},
    lambda v: {**v, 'domain': {**v['domain'], 'document': 12}},
    lambda v: {**v, 'general': {**v['general'], 'model': True}},
    lambda v: {**v, 'general': {**v['general'], 'tables': v['general']['tables'][:-1]}},
    lambda v: {**v, 'input_units': v['input_units'][:1]},
    lambda v: {**v, 'coverage': v['coverage'][:1]},
    lambda v: {**v, 'syntax_sha256': '0'*64},
    lambda v: {**v, 'producer': {**v['producer'], 'engine': '0'*64}},
    lambda v: {**v, 'producer': {**v['producer'], 'syntax_fingerprint': '0'*64}},
])
def test_hostile_exact_closed_typed_transport(owned, mutation):
    from design_graph.model.graph.source_build_ownership import SourceBuildOwnership
    value, _, _ = owned
    with pytest.raises(ValueError):
        SourceBuildOwnership.from_json(json.dumps(mutation(json.loads(value.to_json()))))


def test_finite_preflight_before_json_allocation(owned, monkeypatch):
    from design_graph.model.graph import source_build_ownership as s
    _, reader, _ = owned
    def refused(*a, **k):
        raise AssertionError('JSON allocated before hostile preflight')
    with monkeypatch.context() as patch:
        patch.setattr(s.json, 'loads', refused)
        for text in ('['*257 + '0' + ']'*257, '{"v":"' + 'x'*(s.MAX_JSON_CHARS+1) + '"}'):
            with pytest.raises(ValueError):
                s.SourceBuildOwnership.from_json(text)
    with pytest.raises(ValueError):
        s.SourceBuildOwnership.from_json('{"version":"a","version":"b"}')


def test_unselected_syntax_inventory_mutation_refused_by_retained_anchor(owned):
    from design_graph.model.graph import source_build_ownership as s
    value, reader, db = owned
    anchor = json.loads(Path(str(db)+'.binding.json').read_text())['ownership']
    row = reader._conn.execute('MATCH (s:BindingContextSnapshot) WHERE s.snapshot_id=$id RETURN s.payload', {'id': anchor['snapshot']})
    try:
        payload = row.get_all()[0][0]
    finally:
        row.close()
    changed = json.loads(payload)
    changed['syntax']['captures'][1]['lexical']['ir']['units'][0]['source'] += '\nconst FOREIGN=1;'
    reader._conn.execute('MATCH (s:BindingContextSnapshot) WHERE s.snapshot_id=$id SET s.payload=$payload', {'id': anchor['snapshot'], 'payload': json.dumps(changed)}).close()
    try:
        with pytest.raises(ValueError, match='anchor mismatch'):
            s.load_source_build_ownership(reader)
    finally:
        reader._conn.execute('MATCH (s:BindingContextSnapshot) WHERE s.snapshot_id=$id SET s.payload=$payload', {'id': anchor['snapshot'], 'payload': payload}).close()
    assert s.load_source_build_ownership(reader) == value
