"""Append-only qualified syntax snapshots; no legacy graph ownership inference.

The physical bounded JSON table is shared, the logical envelope is not. A
caller-retained digest can anchor capture custody; a digest in this DB cannot
authenticate coherent fact rewrites or source-to-AST derivation.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from hashlib import sha256

from design_graph.model.binding_ir import _decode, _object, _validate_typed
from design_graph.model.source_syntax import (
    MAX_UNITS,
    CandidateSelection,
    SourceInventory,
    SourceSyntaxCapture,
    _finite,
    project_candidates,
)

from .binding_context import (
    MAX_JSON_CHARS,
    PHYSICAL_VERSION,
    _admit,
    _check_schema,
    _has_extension,
    _json,
    _rollback,
    _rows,
    _write_checked_context,
)

LOGICAL_VERSION = "source-syntax-context/1"


def _digest_token(value):
    if type(value) is not str or re.fullmatch("[0-9a-f]{64}", value) is None:
        raise ValueError("invalid qualified snapshot/digest")


@dataclass(frozen=True)
class SyntaxUnitIdentity:
    unit: str
    locator: str
    source_sha256: str
    source_type: str
    syntax: str
    producer_fingerprint: str


def _inventory(captures):
    return tuple(
        SyntaxUnitIdentity(
            c.source_syntax.unit,
            c.lexical.ir.units[0].locator,
            c.lexical.ir.units[0].source_sha256,
            c.lexical.source_type,
            c.lexical.syntax,
            c.producer_fingerprint,
        )
        for c in captures
    )


@dataclass(frozen=True)
class SourceSyntaxSnapshot:
    version: str
    scope: SourceInventory
    inventory: tuple[SyntaxUnitIdentity, ...]
    captures: tuple[SourceSyntaxCapture, ...]

    @classmethod
    def create(cls, scope, captures):
        if type(captures) is not tuple or not 0 < len(captures) <= MAX_UNITS:
            raise ValueError("finite immutable source syntax capture inventory required")
        _finite((scope, captures))
        _validate_typed(SourceInventory, scope)
        for capture in captures:
            _validate_typed(SourceSyntaxCapture, capture)
        value = cls(LOGICAL_VERSION, scope, _inventory(captures), captures)
        value.check()
        return value

    def check(self):
        _finite(self)
        _validate_typed(SourceSyntaxSnapshot, self)
        if self.version != LOGICAL_VERSION:
            raise ValueError(
                "unsupported source syntax context version; legacy syntax unknown"
            )
        _digest_token(self.scope.snapshot)
        if not self.scope.input_artifact or len(self.scope.input_artifact) > 4096:
            raise ValueError("explicit bounded input artifact required")
        if not 0 < len(self.captures) <= MAX_UNITS:
            raise ValueError("source syntax unit budget exceeded")
        units = tuple(c.source_syntax.unit for c in self.captures)
        if len(set(units)) != len(units) or self.scope.units != units:
            raise ValueError("duplicate or mixed source inventory scope")
        for capture in self.captures:
            capture.check()
            unit = capture.lexical.ir.units[0]
            identity = (
                "u:"
                + sha256(
                    json.dumps(
                        [
                            unit.locator,
                            capture.lexical.source_type,
                            capture.lexical.syntax,
                            unit.source_sha256,
                        ],
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
            )
            if unit.id != identity:
                raise ValueError("noncanonical qualified source unit identity")
        if self.inventory != _inventory(self.captures):
            raise ValueError("source hash/producer inventory mismatch")

    def _body(self):
        return _json(asdict(self))

    def digest(self):
        return _prepare_syntax(self).digest

    def to_json(self):
        return _prepare_syntax(self).payload

    @classmethod
    def from_json(cls, text):
        return _decode_syntax(text).snapshot


@dataclass(frozen=True)
class _AdmittedSyntax:
    snapshot: SourceSyntaxSnapshot
    body: str
    payload: str
    digest: str


def _prepare_syntax(snapshot):
    # Private, invocation-local facts only. Public calls always enter admission.
    SourceSyntaxSnapshot.check(snapshot)
    body = snapshot._body()
    _admit(body)
    digest = sha256(body.encode()).hexdigest()
    payload = '{"sha256":' + _json(digest) + ',"snapshot":' + body + '}'
    _admit(payload)
    return _AdmittedSyntax(snapshot, body, payload, digest)


def _decode_syntax(text):
    _admit(text)  # BEFORE decoding/allocating hostile transport
    try:
        data = json.loads(text, object_pairs_hook=_object)
        if type(data) is not dict or set(data) != {"sha256", "snapshot"}:
            raise ValueError("closed source syntax envelope required")
        _digest_token(data['sha256'])
        admitted = _prepare_syntax(_decode(SourceSyntaxSnapshot, data['snapshot']))
        if admitted.digest != data['sha256']:
            raise ValueError("source syntax payload digest mismatch")
        return admitted
    except (RecursionError, TypeError, UnicodeError) as exc:
        raise ValueError("invalid source syntax transport") from exc


@dataclass(frozen=True)
class _PreparedWrite:
    payload: str
    revision: str


def write_source_syntax(connection, snapshot: SourceSyntaxSnapshot):
    """Own transaction; CREATE collision refuses even a changed reused identity."""
    _finite(snapshot)
    _validate_typed(SourceSyntaxSnapshot, snapshot)
    return _write_checked_context(
        connection, _PreparedWrite(snapshot.to_json(), snapshot.scope.snapshot)
    )


def _read_admitted(connection, snapshot, expected_sha256):
    if not _has_extension(connection):
        return None
    _check_schema(connection)
    metadata = _rows(
        connection,
        "MATCH (s:BindingContextSnapshot) WHERE s.snapshot_id=$id RETURN s.format, size(s.payload)",
        {"id": snapshot},
    )
    if len(metadata) != 1:
        raise ValueError("missing qualified source syntax snapshot")
    physical, size = metadata[0]
    if physical != PHYSICAL_VERSION or type(size) is not int:
        raise ValueError("unsupported physical source syntax version")
    if not 0 < size <= MAX_JSON_CHARS:
        raise ValueError("source syntax pre-fetch character budget exceeded")
    rows = _rows(
        connection,
        "MATCH (s:BindingContextSnapshot) WHERE s.snapshot_id=$id RETURN s.payload",
        {"id": snapshot},
    )
    if len(rows) != 1:
        raise ValueError("incomplete source syntax snapshot")
    admitted = _decode_syntax(rows[0][0])
    if admitted.snapshot.scope.snapshot != snapshot:
        raise ValueError("qualified source syntax snapshot identity mismatch")
    if expected_sha256 is not None and admitted.digest != expected_sha256:
        raise ValueError("external capture custody digest mismatch")
    return admitted


def _read(connection, snapshot, expected_sha256):
    admitted = _read_admitted(connection, snapshot, expected_sha256)
    return None if admitted is None else admitted.snapshot


def read_source_syntax(connection, snapshot, *, expected_sha256=None):
    """Re-admit every call, including unselected units; no public checked handle."""
    _digest_token(snapshot)
    if expected_sha256 is not None:
        _digest_token(expected_sha256)
    _rows(connection, "BEGIN TRANSACTION READ ONLY")
    try:
        value = _read(connection, snapshot, expected_sha256)
        _rows(connection, "COMMIT")
        return value
    except Exception:
        _rollback(connection)
        raise


@dataclass(frozen=True)
class QualifiedSyntaxProjection:
    selection: CandidateSelection
    inventory: tuple[SyntaxUnitIdentity, ...]
    capture_sha256: str
    custody: str
    source_payload_ownership: str = "unknown"


def read_project_source_syntax(
    connection, snapshot, *, input_artifact, units, unit, use, expected_sha256=None
):
    value = read_source_syntax(connection, snapshot, expected_sha256=expected_sha256)
    if value is None:
        return None  # Missing physical extension is legacy/unknown, not recapture.
    scope = SourceInventory(snapshot, input_artifact, units)
    _finite(scope)
    _validate_typed(SourceInventory, scope)
    if scope != value.scope:
        raise ValueError("explicit exact source inventory qualification required")
    return QualifiedSyntaxProjection(
        project_candidates(scope, value.captures, unit, use),
        value.inventory,
        value.digest(),
        "external-digest-matched" if expected_sha256 is not None else "unanchored",
    )
