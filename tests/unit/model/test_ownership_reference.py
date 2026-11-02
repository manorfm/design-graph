"""Ownership wire removes only duplicate syntax, never owner facts or custody."""
import json
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

import pytest

from tests.unit.model.test_source_build_ownership import owned, pytestmark as pytestmark


def test_complete_receipt_roundtrip_uses_exact_syntax_reference(owned):
    from design_graph.model.graph.source_build_ownership import SourceBuildOwnership
    value, _, _ = owned
    data = json.loads(value.to_json())
    assert data['syntax'] == {'snapshot': value.build_fingerprint, 'sha256': value.syntax_sha256}
    assert data['owners'] == json.loads(json.dumps(asdict(value)['owners']))
    assert data['witnesses'] == json.loads(json.dumps(asdict(value)['witnesses']))
    assert SourceBuildOwnership.from_json(value.to_json(), syntax=value.syntax) == value
    with pytest.raises(ValueError, match='separately supplied syntax'):
        SourceBuildOwnership.from_json(value.to_json())


def test_embedded_release_receipt_explicitly_refused(owned):
    from design_graph.model.graph.source_build_ownership import SourceBuildOwnership
    value, _, _ = owned
    legacy = asdict(value)
    legacy.update(version='source-build-ownership/2', builder='binding-build/4')
    with pytest.raises(ValueError, match='unsupported source build ownership version'):
        SourceBuildOwnership.from_json(json.dumps(legacy), syntax=value.syntax)


@pytest.mark.parametrize('mutation', ['missing', 'extra', 'snapshot', 'sha256', 'coherent-reference', 'embedded'])
def test_closed_exact_reference_cannot_relabel_syntax(owned, mutation):
    from design_graph.model.graph.source_build_ownership import SourceBuildOwnership
    value, _, _ = owned
    data = json.loads(value.to_json())
    if mutation == 'missing':
        del data['syntax']
    elif mutation == 'extra':
        data['syntax']['checked'] = True
    elif mutation == 'coherent-reference':
        data['syntax']['snapshot'] = data['build_fingerprint'] = 'a' * 64
    elif mutation == 'embedded':
        data['syntax'] = asdict(value.syntax)
    else:
        data['syntax'][mutation] = 'f' * 64
    with pytest.raises(ValueError):
        SourceBuildOwnership.from_json(json.dumps(data), syntax=value.syntax)


def test_public_decoder_readmits_all_supplied_syntax_each_call(owned, monkeypatch):
    from design_graph.model.binding_capture_ir import _CaptureChecker
    from design_graph.model.graph.source_build_ownership import SourceBuildOwnership
    value, _, _ = owned
    original = _CaptureChecker.run
    calls = []
    def run(self):
        calls.append(self)
        return original(self)
    monkeypatch.setattr(_CaptureChecker, 'run', run)
    for n in (1, 2):
        assert SourceBuildOwnership.from_json(value.to_json(), syntax=value.syntax) == value
        # to_json and from_json each independently admit the full inventory.
        assert len(calls) == n * 2 * len(value.syntax.captures)
    foreign = replace(value.syntax, scope=replace(value.syntax.scope, input_artifact='foreign-document'))
    with pytest.raises(ValueError, match='reference mismatch'):
        SourceBuildOwnership.from_json(value.to_json(), syntax=foreign)


@pytest.mark.parametrize('mutation', ['missing', 'foreign', 'coherent-digest', 'oversized', 'wrong-physical'])
def test_next_call_readmits_independently_bounded_referenced_syntax(owned, mutation):
    from design_graph.model.graph import source_build_ownership as s
    from design_graph.model.graph.source_syntax_context import _prepare_syntax
    value, reader, _ = owned
    connection = reader._conn
    key = value.build_fingerprint
    query = 'MATCH (s:BindingContextSnapshot) WHERE s.snapshot_id=$id '
    payload, physical = s._rows(connection, query + 'RETURN s.payload,s.format', {'id': key})[0]
    assert s.load_source_build_ownership(reader) == value
    try:
        if mutation == 'missing':
            s._rows(connection, query + 'DELETE s', {'id': key})
            assert not s._rows(connection, query + 'RETURN s.payload', {'id': key})
        else:
            changed, fmt = payload, physical
            if mutation in ('foreign', 'coherent-digest'):
                foreign = replace(value.syntax, scope=replace(value.syntax.scope, input_artifact='foreign-document'))
                data = json.loads(_prepare_syntax(foreign).payload)
                if mutation == 'foreign':
                    data['sha256'] = value.syntax_sha256
                changed = json.dumps(data)
            elif mutation == 'oversized':
                changed = ' ' * (s.MAX_JSON_CHARS + 1)
            else:
                fmt = 'foreign/1'
            s._rows(connection, query + 'SET s.payload=$payload,s.format=$format', {'id': key, 'payload': changed, 'format': fmt})
            assert s._rows(connection, query + 'RETURN s.payload,s.format', {'id': key}) == [[changed, fmt]]
        with pytest.raises(ValueError):
            s.load_source_build_ownership(reader)
    finally:
        if mutation == 'missing':
            s._rows(connection, 'CREATE (:BindingContextSnapshot {snapshot_id:$id,format:$format,payload:$payload})', {'id': key, 'format': physical, 'payload': payload})
        else:
            s._rows(connection, query + 'SET s.payload=$payload,s.format=$format', {'id': key, 'payload': payload, 'format': physical})
        assert s._rows(connection, query + 'RETURN s.payload,s.format', {'id': key}) == [[payload, physical]]
    assert s.load_source_build_ownership(reader) == value


@pytest.mark.parametrize('mutation', ['drop-owner', 'reference', 'digest', 'roots', 'old-completion'])
def test_coherent_rehash_cannot_bypass_general_reference_or_completion_checks(owned, mutation):
    from design_graph.model.graph import source_build_ownership as s
    value, reader, db = owned
    seal = Path(str(db) + '.binding.json')
    raw = seal.read_bytes()
    completion = json.loads(raw)
    key = completion['ownership']['snapshot']
    query = 'MATCH (s:BindingContextSnapshot) WHERE s.snapshot_id=$id '
    payload = s._rows(reader._conn, query + 'RETURN s.payload', {'id': key})[0][0]
    data = json.loads(payload)
    assert s.load_source_build_ownership(reader) == value
    try:
        if mutation == 'roots':
            completion['roots'] = []
        elif mutation == 'old-completion':
            completion['contract'] = 'binding-build/4'
        else:
            if mutation == 'drop-owner':
                index = next(i for i, o in enumerate(data['owners']) if o['table'] not in ('Component', 'Screen'))
                del data['owners'][index]
            elif mutation == 'reference':
                data['syntax']['snapshot'] = data['build_fingerprint'] = 'f' * 64
            else:
                data['syntax']['sha256'] = data['syntax_sha256'] = 'f' * 64
            changed = json.dumps(data)
            s._rows(reader._conn, query + 'SET s.payload=$payload', {'id': key, 'payload': changed})
            assert s._rows(reader._conn, query + 'RETURN s.payload', {'id': key}) == [[changed]]
            completion['ownership']['sha256'] = sha256(changed.encode()).hexdigest()
        seal.write_text(json.dumps(completion))
        assert json.loads(seal.read_text()) == completion
        with pytest.raises(ValueError):
            s.load_source_build_ownership(reader)
    finally:
        s._rows(reader._conn, query + 'SET s.payload=$payload', {'id': key, 'payload': payload})
        seal.write_bytes(raw)
        assert seal.read_bytes() == raw
        assert s._rows(reader._conn, query + 'RETURN s.payload', {'id': key}) == [[payload]]
    assert s.load_source_build_ownership(reader) == value
