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


@pytest.mark.parametrize('method', ['check', 'digest', 'to_json'])
def test_public_receipt_each_call_admitted_once_then_rejects_unselected(owned, monkeypatch, method):
    from design_graph.model import binding_capture_ir as ir
    value, _, _ = owned
    original = ir._CaptureChecker.run
    calls = []
    def run(self):
        calls.append(self)
        return original(self)
    monkeypatch.setattr(ir._CaptureChecker, 'run', run)
    for n in (1, 2):
        getattr(value, method)()
        assert len(calls) == n * len(value.syntax.captures)
    captures = value.syntax.captures
    bad_unit = replace(captures[-1].lexical.ir.units[0], source='foreign')
    bad_ir = replace(captures[-1].lexical.ir, units=(bad_unit,))
    bad_capture = replace(captures[-1], lexical=replace(captures[-1].lexical, ir=bad_ir))
    bad = replace(value, syntax=replace(value.syntax, captures=captures[:-1] + (bad_capture,)))
    with pytest.raises(ValueError):
        getattr(bad, method)()


def test_each_owned_read_has_one_property_admission_and_rereads_seal(owned, monkeypatch):
    from design_graph.model.graph import source_build_ownership as s
    from design_graph.pipeline import binding_general_completion as general
    value, reader, db = owned
    original = general.property_receipt
    calls = []
    def receipt(connection):
        calls.append(connection)
        return original(connection)
    monkeypatch.setattr(general, 'property_receipt', receipt)
    for n in (1, 2):
        assert s.load_source_build_ownership(reader) == value
        assert len(calls) == n
    seal = Path(str(db) + '.binding.json')
    payload = seal.read_bytes()
    data = json.loads(payload)
    data['ownership']['sha256'] = '0' * 64
    try:
        seal.write_text(json.dumps(data))
        with pytest.raises(ValueError, match='anchor mismatch'):
            s.load_source_build_ownership(reader)
    finally:
        seal.write_bytes(payload)
    assert s.load_source_build_ownership(reader) == value
