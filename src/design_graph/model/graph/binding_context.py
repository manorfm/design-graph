"""Immutable, bounded binding-capture snapshots in a real Kuzu extension.

This seam owns its transactions, not the caller's Database/Connection handles.
It deliberately does not import the legacy private-context writer or reader.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256

from design_graph.model.binding_capture_ir import BindingCaptureIR
from design_graph.model.binding_ir import CheckResult, _decode, _object, _validate_typed

# Finite whole-snapshot profile; producer source/stdout/time limits are separate.
# Kuzu size(STRING) counts characters: 16 Mi characters bounds UTF8 to 64 MiB
# before fetch. Canonical output is ASCII, making characters the tighter budget.
MAX_JSON_CHARS = 16 * 1024 * 1024
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_RECORDS = 100_000  # all JSON objects, including nested records
MAX_DEPTH = 64  # JSON nesting, distinct from the checker's semantic chain limit
MAX_UNITS = 64
MAX_ROOTS = 4096
LOGICAL_VERSION = "binding-context/2"
PHYSICAL_VERSION = "binding-context-kuzu/1"
TABLE = "BindingContextSnapshot"


def _admit(text: str) -> None:
    """Admit the closed whole-snapshot profile before JSON allocation."""
    _scan_json(text, MAX_JSON_CHARS, MAX_JSON_BYTES, MAX_RECORDS, MAX_DEPTH)


def _scan_json(text, max_chars, max_bytes, max_records, max_depth):
    """Finite scanner shared with the separately bounded completion manifest."""
    if type(text) is not str or len(text) > max_chars:
        raise ValueError("binding context character budget exceeded")
    if len(text.encode("utf-8")) > max_bytes:
        raise ValueError("binding context byte budget exceeded")
    quoted = escaped = False
    depth = records = 0
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            records += char == "{"
            if depth > max_depth or records > max_records:
                raise ValueError("binding context depth/record budget exceeded")
        elif char in "]}":
            depth -= 1
            if depth < 0:
                raise ValueError("invalid binding context JSON nesting")
    if quoted or depth:
        raise ValueError("incomplete binding context JSON")


def _json(value) -> str:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


@dataclass(frozen=True, order=True)
class BindingRoot:
    unit: str
    region: str


@dataclass(frozen=True)
class BindingSnapshot:
    version: str
    community: str
    captures: tuple[BindingCaptureIR, ...]
    roots: tuple[BindingRoot, ...]

    @classmethod
    def create(cls, community, captures, roots):
        value = cls(LOGICAL_VERSION, community, tuple(captures), tuple(roots))
        value.validate()
        return value

    def validate(self) -> None:
        _validate_typed(BindingSnapshot, self)
        self._check_decoded()

    def _check_decoded(self) -> tuple[CheckResult, ...]:
        value = self
        if (
            value.version != LOGICAL_VERSION
            or not value.community
            or len(value.community) > 256
        ):
            raise ValueError("unsupported binding context version/community")
        if not 1 <= len(value.captures) <= MAX_UNITS:
            raise ValueError("invalid binding context unit budget")
        if not 1 <= len(value.roots) <= MAX_ROOTS or len(set(value.roots)) != len(
            value.roots
        ):
            raise ValueError("duplicate or invalid qualified root inventory")
        units = {}
        results = []
        for capture in value.captures:
            # Recompute origin and nearest lookup, never derive facts from targets.
            results.append(capture._check_decoded())
            unit = capture.ir.units[0]
            identity = (
                "u:"
                + sha256(
                    json.dumps(
                        [
                            unit.locator,
                            capture.source_type,
                            capture.syntax,
                            unit.source_sha256,
                        ],
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
            )
            if unit.id != identity or unit.id in units:
                raise ValueError("duplicate or noncanonical qualified source unit")
            units[unit.id] = capture
        for root in value.roots:
            capture = units.get(root.unit)
            region = (
                next((r for r in capture.ir.regions if r.id == root.region), None)
                if capture
                else None
            )
            if region is None or region.slot.value not in ("root", "function-creation"):
                raise ValueError(
                    "root must identify a whole unit or function creation site"
                )

        return tuple(results)

    def to_json(self) -> str:
        return _prepare_snapshot(self).payload

    def _canonical_json(self) -> str:
        data = {
            "version": self.version,
            "community": self.community,
            "captures": [
                c._canonical_data()
                for c in sorted(self.captures, key=lambda c: c.ir.units[0].id)
            ],
            "roots": [asdict(r) for r in sorted(self.roots)],
        }
        text = _json(data)
        _admit(text)
        return text

    @classmethod
    def from_json(cls, text: str):
        return _decode_snapshot(text).snapshot

    def digest(self) -> str:
        return _prepare_snapshot(self).revision


@dataclass(frozen=True)
class _CheckedSnapshot:
    """Invocation-local work, not a caller-supplied credential or public transport.

    Private Python calls are not a security boundary. Ordinary APIs never accept
    this context, and no context is retained on public snapshot objects or caches.
    """

    snapshot: BindingSnapshot
    results: tuple[CheckResult, ...]
    payload: str
    revision: str


def _finish_snapshot(snapshot, results):
    payload = snapshot._canonical_json()
    return _CheckedSnapshot(
        snapshot, results, payload, sha256(payload.encode("utf-8")).hexdigest()
    )


def _prepare_snapshot(snapshot):
    _validate_typed(BindingSnapshot, snapshot)
    return _finish_snapshot(snapshot, snapshot._check_decoded())


def _decode_snapshot(text):
    _admit(text)
    try:
        data = json.loads(
            text,
            object_pairs_hook=_object,
            parse_constant=lambda _: (_ for _ in ()).throw(
                ValueError("nonfinite JSON")
            ),
        )
        snapshot = _decode(BindingSnapshot, data)
        return _finish_snapshot(snapshot, snapshot._check_decoded())
    except (RecursionError, TypeError, UnicodeError) as exc:
        raise ValueError("invalid binding context transport") from exc


def _rows(connection, query, parameters=None):
    result = connection.execute(query, parameters or {})
    try:
        return result.get_all()
    finally:
        result.close()


def _has_extension(connection):
    return TABLE in {
        row[0] for row in _rows(connection, "CALL show_tables() RETURN name")
    }


def _check_schema(connection):
    rows = _rows(connection, "CALL table_info('BindingContextSnapshot') RETURN *")
    actual = {(r[1], r[2], r[4]) for r in rows}
    expected = {
        ("snapshot_id", "STRING", True),
        ("format", "STRING", False),
        ("payload", "STRING", False),
    }
    if len(rows) != 3 or actual != expected:
        raise ValueError("partial or incompatible binding context physical schema")


def _rollback(connection):
    try:
        _rows(connection, "ROLLBACK")
    except RuntimeError as exc:
        # Kuzu automatically aborts on binder/execution errors. Preserve the
        # original failure instead of replacing it with a spurious rollback.
        if str(exc) != "No active transaction for ROLLBACK.":
            raise


def write_binding_context(connection, snapshot: BindingSnapshot) -> str:
    """Append an immutable snapshot atomically; never replace an old capture.

    Caller supplies a real Kuzu connection, with no transaction already active.
    Schema + row commit together; duplicate revision is an error, not an upsert.
    """
    return _write_checked_context(connection, _prepare_snapshot(snapshot))


def _write_checked_context(connection, checked):
    payload, revision = checked.payload, checked.revision
    _rows(connection, "BEGIN TRANSACTION")
    try:
        _rows(
            connection,
            "CREATE NODE TABLE IF NOT EXISTS BindingContextSnapshot("
            "snapshot_id STRING PRIMARY KEY, format STRING, payload STRING)",
        )
        _check_schema(connection)
        _rows(
            connection,
            "CREATE (:BindingContextSnapshot {snapshot_id: $id, format: $format, payload: $payload})",
            {"id": revision, "format": PHYSICAL_VERSION, "payload": payload},
        )
        _rows(connection, "COMMIT")
    except Exception:
        _rollback(connection)
        raise
    return revision


def _read(connection, revision, expected_sha256):
    if not _has_extension(connection):
        return None  # legacy/unknown, NEVER reconstruct or auto-upgrade
    _check_schema(connection)
    metadata = _rows(
        connection,
        "MATCH (s:BindingContextSnapshot) WHERE s.snapshot_id=$id "
        "RETURN s.format, size(s.payload)",
        {"id": revision},
    )
    if len(metadata) != 1:
        raise ValueError("missing or ambiguous binding snapshot")
    format_, characters = metadata[0]
    if format_ != PHYSICAL_VERSION or type(characters) is not int:
        raise ValueError("missing or unsupported physical binding context version")
    if not 0 < characters <= MAX_JSON_CHARS:
        raise ValueError("binding context pre-fetch character budget exceeded")
    rows = _rows(
        connection,
        "MATCH (s:BindingContextSnapshot) WHERE s.snapshot_id=$id RETURN s.payload",
        {"id": revision},
    )
    if len(rows) != 1:
        raise ValueError("incomplete binding snapshot")
    checked = _decode_snapshot(rows[0][0])
    actual = checked.revision
    if actual != revision or (
        expected_sha256 is not None and actual != expected_sha256
    ):
        raise ValueError("binding snapshot commitment or external digest mismatch")
    return checked


def read_binding_context(
    connection, revision: str, *, expected_sha256: str | None = None
):
    """Read in one read-only transaction; no Node/parser/subprocess fallback.

    expected_sha256 is OPTIONAL caller-trusted, independently retained capture
    commitment. A digest obtained from this same mutable DB is NOT an anchor.
    Even with an anchor, the semantic checker reports IR_ONLY, not runtime value
    or producer correctness. Operational/catalog errors propagate fail-closed.
    """
    checked = _read_checked_context(
        connection, revision, expected_sha256=expected_sha256
    )
    return checked.snapshot if checked is not None else None


def _read_checked_context(connection, revision, *, expected_sha256=None):
    if (
        type(revision) is not str
        or len(revision) != 64
        or any(c not in "0123456789abcdef" for c in revision)
    ):
        raise ValueError("invalid snapshot revision")
    if expected_sha256 is not None and (
        type(expected_sha256) is not str
        or len(expected_sha256) != 64
        or any(c not in "0123456789abcdef" for c in expected_sha256)
    ):
        raise ValueError("invalid external capture digest")
    _rows(connection, "BEGIN TRANSACTION READ ONLY")
    try:
        value = _read(connection, revision, expected_sha256)
        _rows(connection, "COMMIT")
        return value
    except Exception:
        _rollback(connection)
        raise
