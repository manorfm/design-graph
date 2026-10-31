"""Finite field-emission provenance; exact slices are not inferred by readers."""
from dataclasses import dataclass, replace
from hashlib import sha256

from design_graph.model.binding_ir import _validate_typed

VERSION = 'source-owner-witness/1'

@dataclass(frozen=True)
class SourceOwnerOrigin:
    unit: str
    locator: str
    source_sha256: str
    native_region: str
    start: int
    end: int

@dataclass(frozen=True)
class SourceOwnerWitness:
    version: str
    table: str
    key: str
    field: str
    payload_sha256: str
    mapping: str
    origins: tuple[SourceOwnerOrigin, ...]

    @property
    def native_region(self):
        return self.origins[0].native_region if len(self.origins) == 1 else None


def emitted(table, key, payload, origin, original):
    from design_graph.pipeline.binding_completion import canonical
    return SourceOwnerWitness(VERSION, table, canonical([key]), 'source_code', sha256(payload.encode()).hexdigest(), 'exact-slice' if payload == original else 'unsupported-derivation', (origin,))


def merged(variants, payload):
    witnesses = [v.source_owner for v in variants]
    if not any(witnesses):
        return None
    first = next(w for w in witnesses if w is not None)
    origins = tuple(dict.fromkeys(o for w in witnesses if w is not None for o in w.origins))
    # Even duplicate equal fragments are distinct producers, not a unique owner.
    if len(witnesses) == 1:
        return first
    return replace(first, payload_sha256=sha256(payload.encode()).hexdigest(), mapping='unsupported-derivation', origins=origins)


def check_witnesses(witnesses, owners, syntax):
    from design_graph.model.graph.source_syntax_context import _digest_token
    if type(witnesses) is not tuple or len(witnesses) > 100_000:
        raise ValueError('invalid bounded owner witness inventory')
    expected = {(o.table, o.key, o.field): o.raw_sha256 for o in owners if o.table in ('Component', 'Screen') and o.field == 'source_code'}
    actual = {}
    units = {c.lexical.ir.units[0].id: c.lexical.ir.units[0] for c in syntax.captures}
    regions = {(c.lexical.ir.units[0].id, r.id): r for c in syntax.captures for r in c.lexical.ir.regions}
    for w in witnesses:
        _validate_typed(SourceOwnerWitness, w)
        identity = (w.table, w.key, w.field)
        if w.version != VERSION or w.mapping not in ('exact-slice', 'unsupported-derivation') or identity not in expected or identity in actual or w.payload_sha256 != expected[identity]:
            raise ValueError('missing/duplicate/stale/wrong-domain owner witness')
        _digest_token(w.payload_sha256)
        if len(w.origins) > 4096 or (not w.origins and w.mapping == 'exact-slice') or len(set(w.origins)) != len(w.origins):
            raise ValueError('invalid native origin inventory')
        if w.mapping == 'exact-slice' and len(w.origins) != 1:
            raise ValueError('mixed native source cannot be an exact slice')
        for origin in w.origins:
            unit = units.get(origin.unit); region = regions.get((origin.unit, origin.native_region))
            if unit is None or region is None or (origin.locator, origin.source_sha256) != (unit.locator, unit.source_sha256):
                raise ValueError('foreign/stale native owner unit')
            if not 0 <= origin.start < origin.end <= unit.byte_length or not region.start <= origin.start < origin.end <= region.end:
                raise ValueError('invalid native owner UTF8 interval')
            if w.mapping == 'exact-slice' and (region.slot.value != 'function-creation' or (origin.start, origin.end) != (region.start, region.end)):
                raise ValueError('exact field requires its native function creation owner')
            raw = unit.source.encode(); raw[:origin.start].decode(); raw[:origin.end].decode()
            if w.mapping == 'exact-slice' and sha256(raw[origin.start:origin.end]).hexdigest() != w.payload_sha256:
                raise ValueError('owner exact slice differs from emitted field')
        actual[identity] = w.payload_sha256
    if actual != expected:
        raise ValueError('missing source field witness')
