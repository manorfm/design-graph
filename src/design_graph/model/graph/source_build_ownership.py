"""Trusted local BUILD receipts, not authentication or precise JS owner selection.

The independently retained completion seal is required. Never accept a requester's
provenance flag/digest, infer ownership from singleton snapshots, or recapture here.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

from design_graph.model.binding_ir import _decode, _object, _validate_typed
from design_graph.model.graph.binding_context import (
    MAX_JSON_CHARS,
    PHYSICAL_VERSION,
    _admit,
    _check_schema,
    _CheckedSnapshot,
    _has_extension,
    _json,
    _rows,
    _write_checked_context,
)
from design_graph.model.graph.schema import MODEL_VERSION
from design_graph.model.graph.source_syntax_context import (
    SourceSyntaxSnapshot,
    _digest_token,
    _prepare_syntax,
    _PreparedWrite,
)
from design_graph.model.source_owner import SourceOwnerWitness, check_witnesses
from design_graph.model.source_syntax import _finite

VERSION = 'source-build-ownership/2'
BUILDER = 'binding-build/4'


@dataclass(frozen=True)
class DocumentDomain:
    document: str
    screens: tuple[str, ...]


@dataclass(frozen=True)
class InputUnit:
    locator: str
    source_sha256: str
    byte_length: int
    source_type: str
    syntax: str


@dataclass(frozen=True)
class CoverageRecord:
    locator: str
    status: str
    mime: str
    reason: str | None = None
    order: int | None = None
    src: str | None = None
    source_type: str | None = None
    syntax: str | None = None
    async_: bool | None = None
    defer: bool | None = None
    source_sha256: str | None = None
    byte_length: int | None = None


@dataclass(frozen=True)
class ArtifactPin:
    locator: str
    sha256: str


@dataclass(frozen=True)
class ProducerIdentity:
    engine: str
    syntax_fingerprint: str
    adaptor: tuple[ArtifactPin, ...]


@dataclass(frozen=True)
class PayloadOwner:
    table: str
    key: str
    field: str
    payload_sha256: str
    raw_sha256: str = ''


@dataclass(frozen=True)
class TableCommitment:
    table: str
    schema: str
    count: int
    properties_sha256: str


@dataclass(frozen=True)
class GeneralCommitment:
    version: str
    model: int
    capture: str
    identity_sha256: str
    tables: tuple[TableCommitment, ...]


@dataclass(frozen=True)
class SourceBuildOwnership:
    version: str
    builder: str
    domain: DocumentDomain
    input_locator: str
    input_sha256: str
    input_bytes: int
    input_units: tuple[InputUnit, ...]
    coverage: tuple[CoverageRecord, ...]
    producer: ProducerIdentity
    build_fingerprint: str
    lexical_snapshot: str
    general: GeneralCommitment
    owners: tuple[PayloadOwner, ...]
    syntax_sha256: str
    syntax: SourceSyntaxSnapshot
    witnesses: tuple[SourceOwnerWitness, ...] = ()
    granularity: str = 'field emission native owner; unsupported derivations explicit'

    def check(self):
        _check_receipt(self, _prepare_syntax(self.syntax))

    def to_json(self):
        return _prepare_receipt(self).payload

    def digest(self):
        return _prepare_receipt(self).digest

    @classmethod
    def from_json(cls, text):
        return _decode_receipt(text)


def _check_receipt(self, admitted):
    _finite(self)
    _validate_typed(SourceBuildOwnership, self)
    if self.version != VERSION or self.builder != BUILDER:
        raise ValueError('unsupported source build ownership version')
    if self.general.version != 'binding-general-properties/1' or self.general.model != MODEL_VERSION or self.general.capture != 'html_prototype':
        raise ValueError('incompatible ownership model')
    if self.granularity != 'field emission native owner; unsupported derivations explicit':
        raise ValueError('unsupported ownership granularity')
    if not self.domain.document or len(self.domain.document) > 4096 or not self.domain.screens or tuple(sorted(set(self.domain.screens))) != self.domain.screens:
        raise ValueError('invalid selected document/Screen domain')
    if self.input_locator != self.syntax.scope.input_artifact or not 0 <= self.input_bytes <= 64 * 1024 * 1024:
        raise ValueError('invalid ownership input')
    for token in (self.input_sha256, self.build_fingerprint, self.lexical_snapshot, self.syntax_sha256, self.general.identity_sha256):
        _digest_token(token)
    if admitted.snapshot is not self.syntax:
        raise ValueError('private syntax admission identity mismatch')
    if self.syntax.scope.snapshot != self.build_fingerprint:
        raise ValueError('syntax inventory build identity mismatch')
    if admitted.digest != self.syntax_sha256:
        raise ValueError('ownership syntax digest mismatch')
    actual = tuple(InputUnit(c.lexical.ir.units[0].locator, c.lexical.ir.units[0].source_sha256, c.lexical.ir.units[0].byte_length, c.lexical.source_type, c.lexical.syntax) for c in self.syntax.captures)
    if actual != self.input_units:
        raise ValueError('ownership complete input inventory mismatch')
    if len(self.general.tables) != 39 or len({t.table for t in self.general.tables}) != 39:
        raise ValueError('incomplete ownership table inventory')
    for table in self.general.tables:
        if not 0 <= table.count <= 100_000:
            raise ValueError('ownership row budget exceeded')
        _digest_token(table.properties_sha256)
    if len(self.owners) > 100_000:
        raise ValueError('ownership payload budget exceeded')
    for owner in self.owners:
        _digest_token(owner.payload_sha256)
    for token in (self.producer.engine, self.producer.syntax_fingerprint):
        _digest_token(token)
    if not self.producer.adaptor or len(self.producer.adaptor) > 128 or len({p.locator for p in self.producer.adaptor}) != len(self.producer.adaptor):
        raise ValueError('invalid producer adaptor inventory')
    for pin in self.producer.adaptor:
        _digest_token(pin.sha256)
    if any(c.lexical.engine_fingerprint != self.producer.engine or c.producer_fingerprint != self.producer.syntax_fingerprint for c in self.syntax.captures):
        raise ValueError('ownership producer mismatch')
    check_witnesses(self.witnesses, self.owners, self.syntax)
    if len(self.coverage) > 4096 or len({v.locator for v in self.coverage}) != len(self.coverage):
        raise ValueError('invalid bounded coverage inventory')
    for record in self.coverage:
        if record.status not in ('captured', 'excluded') or (record.status == 'excluded' and not record.reason):
            raise ValueError('invalid explicit coverage status/reason')
    selected = [v for v in self.coverage if v.status == 'captured']
    if [InputUnit(v.locator, v.source_sha256, v.byte_length, v.source_type, v.syntax) for v in selected] != list(self.input_units):
        raise ValueError('ownership coverage differs from full inventory')

@dataclass(frozen=True)
class _AdmittedReceipt:
    value: SourceBuildOwnership
    payload: str
    digest: str


def _prepare_receipt(value, syntax=None):
    _check_receipt(value, _prepare_syntax(value.syntax) if syntax is None else syntax)
    text = _json(asdict(value))
    _admit(text)
    return _AdmittedReceipt(value, text, sha256(text.encode()).hexdigest())


def _decode_receipt(text):
    _admit(text)  # byte/depth/container scan BEFORE allocation
    try:
        value = _decode(SourceBuildOwnership, json.loads(text, object_pairs_hook=_object))
        value.check()
        return value
    except (TypeError, KeyError, RecursionError, UnicodeError) as exc:
        raise ValueError('invalid source ownership transport') from exc


def receipt_key(domain):
    return sha256((VERSION + ':' + _json(asdict(domain))).encode()).hexdigest()


def selected_domain(connection, document):
    screens = _rows(connection, 'MATCH (s:Screen) RETURN s.name ORDER BY s.name LIMIT 4097')
    if not screens or len(screens) > 4096:
        raise ValueError('missing/bounded selected Screen inventory required')
    return DocumentDomain(document, tuple(row[0] for row in screens))


def create_receipt(connection, stage):
    return _create_receipt(connection, stage, _prepare_syntax(stage.syntax))


def _create_receipt(connection, stage, admitted):
    if admitted.snapshot is not stage.syntax:
        raise ValueError('private syntax admission identity mismatch')
    from design_graph.pipeline.binding_general_completion import property_receipt
    general, owners = property_receipt(connection)
    syntax = stage.syntax
    return SourceBuildOwnership(
        VERSION, BUILDER, stage.domain, stage.manifest['source_path'],
        stage.manifest['source_sha256'], stage.input_bytes,
        tuple(InputUnit(**v) for v in stage.manifest['units']),
        tuple(CoverageRecord(**v) for v in stage.coverage),
        ProducerIdentity(stage.manifest['engine'], stage.manifest['syntax_producer'], tuple(ArtifactPin(k, v) for k, v in sorted(stage.manifest['adaptor'].items()))),
        stage.fingerprint, stage._checked.revision, general, owners,
        admitted.digest, syntax, witnesses=stage.field_witnesses(owners),
    )


def append_receipt(connection, value):
    return _append_admitted_receipt(connection, _prepare_receipt(value))


def _append_admitted_receipt(connection, admitted):
    return _write_checked_context(connection, _PreparedWrite(admitted.payload, receipt_key(admitted.value.domain)))


def _read_owned_facts(connection, domain, anchor):
    """Internal one-invocation admission; anchor comes only from builder seal."""
    from design_graph.pipeline.binding_general_completion import property_receipt
    if type(anchor) is not dict or set(anchor) != {'version', 'snapshot', 'sha256'} or anchor['version'] != VERSION:
        raise ValueError('missing/incompatible ownership completion anchor')
    for k in ('snapshot', 'sha256'):
        _digest_token(anchor[k])
    if anchor['snapshot'] != receipt_key(domain) or not _has_extension(connection):
        raise ValueError('ownership selected document/Screen differs or missing receipt')
    _check_schema(connection)
    metadata = _rows(connection, 'MATCH (s:BindingContextSnapshot) WHERE s.snapshot_id=$id RETURN s.format,size(s.payload)', {'id': anchor['snapshot']})
    if len(metadata) != 1 or metadata[0][0] != PHYSICAL_VERSION or type(metadata[0][1]) is not int or not 0 < metadata[0][1] <= MAX_JSON_CHARS:
        raise ValueError('missing/incompatible ownership receipt or prefetch budget')
    payload = _rows(connection, 'MATCH (s:BindingContextSnapshot) WHERE s.snapshot_id=$id RETURN s.payload', {'id': anchor['snapshot']})[0][0]
    if sha256(payload.encode()).hexdigest() != anchor['sha256']:
        raise ValueError('independently retained ownership anchor mismatch')
    value = SourceBuildOwnership.from_json(payload)
    if value.domain != domain:
        raise ValueError('ownership selected domain mismatch')
    from design_graph.model.graph.source_syntax_context import _read as read_syntax
    syntax = read_syntax(connection, value.syntax.scope.snapshot, value.syntax_sha256)
    if syntax != value.syntax:
        raise ValueError('qualified and embedded syntax inventories differ')
    from design_graph.model.graph.binding_context import _read as read_lexical
    lexical = read_lexical(connection, value.lexical_snapshot, value.lexical_snapshot)
    canonical_captures = lambda captures: _json([c._canonical_data() for c in sorted(captures, key=lambda c: c.ir.units[0].id)])
    if lexical is None or canonical_captures(lexical.snapshot.captures) != canonical_captures(tuple(c.lexical for c in value.syntax.captures)):
        raise ValueError('lexical and syntax inventories differ')
    general, owners = property_receipt(connection)
    if (value.general, value.owners) != (general, owners):
        raise ValueError('current general graph properties differ from ownership receipt')
    return _OwnedRead(value, lexical)


@dataclass(frozen=True)
class _OwnedRead:
    value: SourceBuildOwnership
    lexical: _CheckedSnapshot


def _read_owned(connection, domain, anchor):
    return _read_owned_facts(connection, domain, anchor).value


def load_source_build_ownership(reader):
    return _load_source_build_facts(reader).value


def _load_source_build_facts(reader):
    from design_graph.model.graph.binding_context import _rollback

    connection = reader._conn
    _rows(connection, 'BEGIN TRANSACTION READ ONLY')
    try:
        facts = _read_source_build_facts(reader)
        _rows(connection, 'COMMIT')
        return facts
    except Exception:
        _rollback(connection)
        raise


def _read_source_build_facts(reader):
    """Resolve completion inside the caller's private invocation read transaction.

    No checked flag or facts survive the invocation. The public loader starts its
    own transaction; the automatic consumer also reads its exact selected fields
    before committing the same admission transaction.

    Completion is independently retained OUTSIDE the graph, but remains local
    builder custody, not a signature. Rewriting the seal too can forge consistency.
    """
    from design_graph.model.graph.binding_context import _rollback
    from design_graph.pipeline.binding_completion import read_completion
    state = reader._state_path
    if state is None or not str(state).endswith('.state.json'):
        raise ValueError('ownership unknown: selected reader has no retained build completion')
    db = Path(str(state)[:-len('.state.json')])
    previous = read_completion(Path(str(db) + '.binding.json'))
    if previous.get('contract') != BUILDER:
        raise ValueError('ownership unknown: incompatible completion version')
    identity_keys = {'contract', 'logical', 'physical', 'source_path', 'source_sha256', 'engine', 'syntax_producer', 'options', 'adaptor', 'model', 'units', 'coverage', 'linkage'}
    completion_keys = {'build_fingerprint', 'snapshot', 'roots', 'general', 'ownership'}
    if set(previous) != identity_keys | completion_keys:
        raise ValueError('incompatible ownership completion fields')
    identity = {k: previous[k] for k in identity_keys}
    if type(identity['coverage']) is not list:
        raise ValueError('invalid ownership completion inventory')
    identity['coverage'] = [{**record, 'status': 'selected'} if record.get('status') == 'captured' else record for record in identity['coverage']]
    if sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest() != previous['build_fingerprint']:
        raise ValueError('ownership completion fingerprint mismatch')
    connection = reader._conn
    facts = _read_owned_facts(connection, selected_domain(connection, db.stem), previous.get('ownership'))
    value = facts.value
    if value.build_fingerprint != previous.get('build_fingerprint') or value.lexical_snapshot != previous.get('snapshot'):
        raise ValueError('ownership completion identity mismatch')
    if sha256(_json(previous['general']).encode()).hexdigest() != value.general.identity_sha256:
        raise ValueError('ownership completion general commitment mismatch')
    expected_roots = sorted(({'unit': c.lexical.ir.units[0].id, 'region': r.id} for c in value.syntax.captures for r in c.lexical.ir.regions if r.slot.value in ('root', 'function-creation')), key=_json)
    if _json(sorted(previous['roots'], key=_json)) != _json(expected_roots):
        raise ValueError('ownership completion roots mismatch')
    return facts
