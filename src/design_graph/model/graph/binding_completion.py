"""Bounded completion consistency, not authentication of arbitrary rewrites."""

import json
import re

from design_graph.model.binding_ir import _object
from design_graph.model.serialization import canonical
from design_graph.model.graph.binding_context import _scan_json

# Completion parsing is not the snapshot profile. Retain its smaller independent
# allocation budget even when snapshot admission changes.
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_MANIFEST_RECORDS = 20_000
MAX_MANIFEST_DEPTH = 64


def completed_identity(identity):
    """Only selected inventory transitions to captured after full admission."""
    result = dict(identity)
    result["coverage"] = [
        {**record, "status": "captured"}
        if record["status"] == "selected"
        else dict(record)
        for record in identity["coverage"]
    ]
    return result


def read_completion(path):
    """Bounded independently retained builder seal, never an in-DB flag."""
    with path.open("rb") as stream:
        raw = stream.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("binding manifest byte budget exceeded")
    text = raw.decode("utf8", errors="strict")
    _scan_json(text, MAX_MANIFEST_BYTES, MAX_MANIFEST_BYTES, MAX_MANIFEST_RECORDS, MAX_MANIFEST_DEPTH)
    value = json.loads(text, object_pairs_hook=_object)
    if type(value) is not dict:
        raise ValueError("closed binding completion required")
    return value


def read_manifest(path, identity, fingerprint):
    previous = read_completion(path)
    expected = completed_identity(identity)
    additions = {"build_fingerprint", "snapshot", "roots", "general"}
    if identity.get('contract') == 'binding-build/4':
        additions.add('ownership')
    if type(previous) is not dict or set(previous) != set(expected) | additions:
        raise ValueError("incompatible binding completion fields")
    actual = {key: previous[key] for key in expected}
    if canonical(actual) != canonical(expected):
        raise ValueError("binding completion differs from current input identity")
    if previous["build_fingerprint"] != fingerprint:
        raise ValueError("binding completion fingerprint differs")
    revision = previous["snapshot"]
    if type(revision) is not str or re.fullmatch("[0-9a-f]{64}", revision) is None:
        raise ValueError("invalid binding completion snapshot")
    return previous


def verify_snapshot(snapshot, previous, identity):
    if snapshot is None:
        raise ValueError("missing binding completion snapshot")
    actual = []
    roots = []
    for capture in snapshot.captures:
        unit = capture.ir.units[0]
        actual.append(
            {
                "locator": unit.locator,
                "source_sha256": unit.source_sha256,
                "byte_length": unit.byte_length,
                "source_type": capture.source_type,
                "syntax": capture.syntax,
            }
        )
        if capture.engine_fingerprint != identity["engine"]:
            raise ValueError("binding completion engine differs")
        roots.extend(
            {"unit": unit.id, "region": region.id}
            for region in capture.ir.regions
            if region.slot.value in ("root", "function-creation")
        )
    key = lambda record: canonical(record)
    if canonical(sorted(actual, key=key)) != canonical(
        sorted(identity["units"], key=key)
    ):
        raise ValueError("binding completion units differ")
    stored = [{"unit": root.unit, "region": root.region} for root in snapshot.roots]
    expected = canonical(sorted(roots, key=key))
    if canonical(sorted(stored, key=key)) != expected:
        raise ValueError("binding completion omitted roots")
    if (
        type(previous["roots"]) is not list
        or canonical(sorted(previous["roots"], key=key)) != expected
    ):
        raise ValueError("binding completion roots differ")
