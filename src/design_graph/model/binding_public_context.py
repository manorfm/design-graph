"""Versioned IR-only public binding projection, never a runtime helper selector.

No whole-unit, declaration-token or function-body slices leave this API. All
contributing occurrence records are retained, not defs[0]. A checked span is not
proof that its bytes form an identifier token under a hostile coherent rewrite.
"""

from __future__ import annotations

import json
from functools import partial
from hashlib import sha256

CONTRACT = "binding-public-context/1"


def qualified_identity(community, revision, unit, kind, local):
    parts = [community, revision, unit, kind, local]
    return (
        kind
        + ":"
        + sha256(
            json.dumps(parts, ensure_ascii=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


def _legacy_context():
    return {
        "contract": CONTRACT,
        "availability": "legacy/unknown",
        "evidence": "legacy",
        "initialization": "unknown",
        "value": "unknown",
        "references": [],
        "bindings": [],
        "environments": [],
        "sites": [],
    }


def _belongs_to_root(site, root, regions):
    cursor = regions[site]
    while True:
        if cursor.id == root:
            return True
        if cursor.parent is None:
            return False
        cursor = regions[cursor.parent]


def _select_references(capture, region, regions):
    return sorted(
        (
            r
            for r in capture.ir.references
            if _belongs_to_root(r.region, region, regions)
        ),
        key=lambda r: r.id,
    )


def _reference_environments(refs, resolutions, environments):
    # Retain the full competing-name inventory, not just claimed endpoints.
    env_ids = set()
    for ref in refs:
        cursor = resolutions[ref.id].origin
        while cursor is not None:
            env_ids.add(cursor)
            cursor = environments[cursor].outer
    return env_ids


def _paired_sites(site_ids, regions):
    return {
        r.id
        for r in regions.values()
        if r.parent in site_ids
        and regions[r.parent].slot.value in ("function-creation", "switch")
        and r.slot.value
        in (
            "function-parameters",
            "function-body",
            "switch-discriminant",
            "switch-case",
        )
    }


def _extend_sites(site_ids, regions):
    # Parent expansion precedes paired-slot expansion, as in the original round.
    before = set(site_ids)
    site_ids.update(
        regions[site].parent for site in before if regions[site].parent is not None
    )
    site_ids.update(_paired_sites(site_ids, regions))


def _extend_environments(site_ids, env_ids, regions, environments):
    env_ids.update(
        regions[s].environment for s in site_ids if regions[s].environment is not None
    )
    outers = {
        environments[e].outer for e in env_ids if environments[e].outer is not None
    }
    env_ids.update(outers)
    site_ids.update(environments[e].owner for e in env_ids)


def _close_provenance(region, refs, initial_env_ids, regions, environments):
    """Close ancestors, paired evaluation slots and environment owners/outers.

    Each round only adds inventoried IDs. Equality of both finite sets is the
    fixed point; neither a reference-free root nor an outer owner is skipped.
    Work on local sets, leaving the input inventories unchanged.
    """
    env_ids = set(initial_env_ids)
    site_ids = {
        region,
        *(r.region for r in refs),
        *(environments[e].owner for e in env_ids),
    }
    while True:
        before_sites, before_envs = set(site_ids), set(env_ids)
        _extend_sites(site_ids, regions)
        _extend_environments(site_ids, env_ids, regions, environments)
        if before_sites == site_ids and before_envs == env_ids:
            return site_ids, env_ids


def _select_bindings(capture, refs, env_ids):
    needed_names = {r.name for r in refs}
    return sorted(
        (
            b
            for b in capture.ir.bindings
            if b.environment in env_ids and b.name in needed_names
        ),
        key=lambda b: b.id,
    )


def _serialize_references(refs, resolutions, identity, unit):
    return [_serialize_reference(r, resolutions[r.id], identity, unit) for r in refs]


def _serialize_bindings(capture, bindings, identity, unit):
    occurrences = {d.id: d for d in capture.ir.occurrences}
    return [
        _serialize_binding(b, capture, occurrences, identity, unit) for b in bindings
    ]


def _serialize_environments(environments, env_ids, identity, unit):
    return [
        _serialize_environment(e, identity, unit)
        for e in sorted(environments.values(), key=lambda e: e.id)
        if e.id in env_ids
    ]


def _serialize_sites(regions, site_ids, identity, unit):
    return [
        _serialize_site(r, identity, unit)
        for r in sorted(regions.values(), key=lambda r: r.id)
        if r.id in site_ids
    ]


def _serialize_site_metadata(capture, site_ids, identity):
    return {
        "gaps": [
            {"site": identity("site", g.region), "kind": g.kind}
            for g in sorted(capture.gaps, key=lambda g: (g.region, g.kind))
            if g.region in site_ids
        ],
        "function_sites": [
            {"site": identity("site", f.region), "kind": f.kind}
            for f in sorted(capture.functions, key=lambda f: f.region)
            if f.region in site_ids
        ],
    }


def _serialize_source(capture, unit):
    return {
        "unit": unit,
        "locator": capture.ir.units[0].locator,
        "sha256": capture.ir.units[0].source_sha256,
        "byte_length": capture.ir.units[0].byte_length,
        "source_type": capture.source_type,
        "syntax": capture.syntax,
        "capture_version": capture.version,
        "ir_version": capture.ir.version,
        "semantic_profile": capture.ir.profile,
        "engine_fingerprint": capture.engine_fingerprint,
    }


def _serialize_occurrence(d, identity, unit):
    return {
        "identity": identity("occurrence", d.id),
        "local_id": d.id,
        "unit": unit,
        "environment": identity("environment", d.environment),
        "namespace": d.namespace.value,
        "name": d.name,
        "kind": d.kind.value,
        "start": d.start,
        "end": d.end,
    }


def _serialize_reference(r, resolution, identity, unit):
    return {
        "identity": identity("reference", r.id),
        "local_id": r.id,
        "unit": unit,
        "name": r.name,
        "namespace": r.namespace.value,
        "access": r.access.value,
        "start": r.start,
        "end": r.end,
        "site": identity("site", r.region),
        "origin": identity("environment", resolution.origin),
        "state": resolution.state.value,
        "target": identity("binding", resolution.target) if resolution.target else None,
        "path": [identity("environment", e) for e in resolution.path],
        "initialization": "unknown",
        "value": "unknown",
    }


def _serialize_binding(b, capture, occurrences, identity, unit):
    return {
        "identity": identity("binding", b.id),
        "local_id": b.id,
        "unit": unit,
        "environment": identity("environment", b.environment),
        "namespace": b.namespace.value,
        "name": b.name,
        "occurrences": [
            _serialize_occurrence(occurrences[d], identity, unit)
            for d in sorted(b.occurrences)
        ],
        "intrinsic": next(
            (i.kind for i in capture.intrinsics if i.binding == b.id), None
        ),
        "initialization": "unknown",
        "value": "unknown",
    }


def _serialize_environment(e, identity, unit):
    return {
        "identity": identity("environment", e.id),
        "local_id": e.id,
        "unit": unit,
        "kind": e.kind.value,
        "owner": identity("site", e.owner),
        "outer": identity("environment", e.outer) if e.outer else None,
        "complete": e.complete,
    }


def _serialize_site(r, identity, unit):
    return {
        "identity": identity("site", r.id),
        "local_id": r.id,
        "unit": unit,
        "slot": r.slot.value,
        "parent": identity("site", r.parent) if r.parent else None,
        "environment": identity("environment", r.environment)
        if r.environment
        else None,
        "start": r.start,
        "end": r.end,
        "split_parameters": r.split_parameters,
        "complete": r.complete,
    }


def project_binding_context(snapshot, *, unit: str, region: str):
    """Select ONLY an explicitly inventoried qualified root, never by name.

    This is a reader-checked projection, not a source certificate. The receiver
    can audit target/occurrence/path/site provenance; authenticating the source
    derivation still requires trusted capture custody, not this document's hash.
    """
    if snapshot is None:
        return _legacy_context()
    from design_graph.model.graph.binding_context import _prepare_snapshot

    return _project_checked(_prepare_snapshot(snapshot), unit=unit, region=region)


def read_project_binding_context(
    connection,
    revision: str,
    *,
    unit: str,
    region: str,
    expected_sha256: str | None = None,
):
    """Admit fresh stored bytes and project with that invocation's checked work.

    Accept identifiers and an optional independently retained anchor, never a
    claimed validated handle. A later invocation always reads and checks again.
    """
    from design_graph.model.graph.binding_context import _read_checked_context

    checked = _read_checked_context(
        connection, revision, expected_sha256=expected_sha256
    )
    if checked is None:
        return _legacy_context()
    return _project_checked(checked, unit=unit, region=region)


def _project_checked(checked, *, unit, region):
    snapshot = checked.snapshot
    if not any(root.unit == unit and root.region == region for root in snapshot.roots):
        raise ValueError("unknown qualified public binding root")
    index = next(i for i, c in enumerate(snapshot.captures) if c.ir.units[0].id == unit)
    capture = snapshot.captures[index]
    revision = checked.revision
    identity = partial(qualified_identity, snapshot.community, revision, unit)
    regions = {r.id: r for r in capture.ir.regions}
    environments = {e.id: e for e in capture.ir.environments}
    refs = _select_references(capture, region, regions)
    resolutions = {r.id: r for r in checked.results[index].resolutions}
    env_ids = _reference_environments(refs, resolutions, environments)
    site_ids, env_ids = _close_provenance(region, refs, env_ids, regions, environments)
    bindings = _select_bindings(capture, refs, env_ids)
    return {
        "contract": CONTRACT,
        "availability": "available",
        "community": snapshot.community,
        "snapshot": revision,
        "root": {
            "identity": identity("root", region),
            "unit": unit,
            "region": identity("site", region),
            "local_region": region,
        },
        "evidence": "IR_ONLY",
        "initialization": "unknown",
        "value": "unknown",
        "verification": "reader-recomputed-static-unit-lookup; origin-not-authenticated-by-document",
        "source": _serialize_source(capture, unit),
        "references": _serialize_references(refs, resolutions, identity, unit),
        "bindings": _serialize_bindings(capture, bindings, identity, unit),
        "environments": _serialize_environments(environments, env_ids, identity, unit),
        "sites": _serialize_sites(regions, site_ids, identity, unit),
        **_serialize_site_metadata(capture, site_ids, identity),
    }
