"""Bounded name fallback over one selected reader's admitted lexical snapshot.

This delivers persisted source context, not runtime values or member linkage.
No parser, global database discovery, source-unit dump or cross-call cache.
"""

from __future__ import annotations

from hashlib import sha256

from design_graph.interface.mcp.qualified_source_tool import (
    COVERAGE_NOTICE,
    MAX_SOURCE_BYTES,
    part_number,
)
from design_graph.model.graph.binding_context import (
    _has_extension,
    read_binding_context,
)

MAX_CONTEXTS = 64
MAX_REFERENCES = 4096


def _one(items, reason):
    if len(items) != 1:
        raise ValueError("automatic source: missing or ambiguous " + reason)
    return items[0]


def _declaration(capture, binding):
    occurrences = {d.id: d for d in capture.ir.occurrences}
    return _one([occurrences[i] for i in binding.occurrences], "declaration occurrence")


def _function(capture, declaration):
    if declaration.kind.value != "function":
        raise ValueError("automatic source: no captured function declaration context")
    candidates = [
        r
        for r in capture.ir.regions
        if r.unit == declaration.unit
        and r.slot.value == "function-creation"
        and r.start <= declaration.start < declaration.end <= r.end
    ]
    if not candidates:
        raise ValueError("automatic source: no captured function region")
    width = min(r.end - r.start for r in candidates)
    return _one(
        [r for r in candidates if r.end - r.start == width], "smallest function region"
    )


def _context(capture, binding, revision, *, function=False):
    declaration = _declaration(capture, binding)
    unit = capture.ir.units[0]
    raw = unit.source.encode("utf-8")
    region = _function(capture, declaration) if function else None
    if region:
        start, end = region.start, region.end
        selection = "persisted function region containing declaration identifier; not a runtime value"
    else:
        # A line is only source context. Never guess initializer/declaration ends.
        start = raw.rfind(b"\n", 0, declaration.start) + 1
        end = raw.find(b"\n", declaration.end)
        if end < 0:
            end = len(raw)
        selection = (
            "declaration-identifier line source context; full declaration/initializer extent "
            "unknown (including multiline continuation); not a runtime value"
        )
    if region is None and start == 0 and end == len(raw):
        raise ValueError(
            "automatic source: bounded declaration line context unknown; refusing whole-unit dump"
        )
    if not 0 <= start < end <= len(raw) or end - start > MAX_SOURCE_BYTES:
        raise ValueError("automatic source: source byte budget exceeded")
    body = raw[start:end]
    return {
        "snapshot": revision,
        "unit": unit.id,
        "region": region.id if region else "unknown",
        "interval": [start, end],
        "unit_sha256": unit.source_sha256,
        "source_sha256": sha256(body).hexdigest(),
        "source": body.decode("utf-8"),
        "syntax": capture.syntax,
        "binding": binding.id,
        "occurrence": declaration.id,
        "selection": selection,
    }


def _records(snapshot, name, revision):
    capture, binding = _one(
        [
            (c, b)
            for c in snapshot.captures
            for b in c.ir.bindings
            if b.name == name and b.occurrences
        ],
        "declared name in snapshot",
    )
    root = _context(capture, binding, revision, function=True)
    regions = {r.id: r for r in capture.ir.regions}
    bindings = {b.id: b for b in capture.ir.bindings}
    resolutions = {r.id: r for r in capture.ir.resolutions}
    if len(capture.ir.references) > MAX_REFERENCES:
        raise ValueError("automatic source: reference budget exceeded")
    records = [root]
    seen = {binding.id}
    visited = set()
    queue = [root["region"]]
    total = len(root["source"].encode("utf-8"))
    while queue:
        rid = queue.pop(0)
        if rid in visited:
            continue
        visited.add(rid)
        region = regions[rid]
        for ref in capture.ir.references:
            if not region.start <= ref.start < ref.end <= region.end:
                continue
            resolution = resolutions[ref.id]
            target = bindings.get(resolution.target)
            if (
                resolution.state.value != "resolved"
                or target is None
                or target.id in seen
            ):
                continue
            seen.add(target.id)
            if not target.occurrences:
                continue
            declaration = _declaration(capture, target)
            # Already visible within an emitted function; do not duplicate its locals.
            if any(
                a["interval"][0]
                <= declaration.start
                < declaration.end
                <= a["interval"][1]
                for a in records
            ):
                continue
            rec = _context(
                capture, target, revision, function=declaration.kind.value == "function"
            )
            total += len(rec["source"].encode("utf-8"))
            if len(records) >= MAX_CONTEXTS or total > MAX_SOURCE_BYTES:
                raise ValueError(
                    "automatic source: aggregate record/byte budget exceeded"
                )
            records.append(rec)
            if rec["region"] != "unknown":
                queue.append(rec["region"])
    return records


def _snapshot(connection):
    if not _has_extension(connection):
        return None, None
    rows = connection.execute(
        "MATCH (s:BindingContextSnapshot) RETURN s.snapshot_id LIMIT 2"
    )
    try:
        revisions = []
        while rows.has_next():
            revisions.append(rows.get_next()[0])
    finally:
        rows.close()
    revision = _one(
        revisions, "persisted snapshot in selected reader (no latest selection)"
    )
    # Full hostile-input admission exactly once, reused only within this invocation.
    return read_binding_context(connection, revision), revision


def _ownership_unknown(reader, snapshot, revision):
    """Current legacy records cannot associate a checked inventory to a build.

    Model stores only version/capture, and legacy source rows have no document,
    build, snapshot or unit identity. The optional state file is a build diff;
    the binding completion's general receipt commits keys/edges, not source
    payloads. Neither can exclude stale same-shape builds or mixed communities.
    A unique whole component/region byte match would establish only a shared
    fragment, not ownership of the snapshot's other units or helper declarations.
    Do not upgrade those facts into a document-wide source association.
    """
    return (
        "Source ownership/correspondence unknown: selected legacy graph has no "
        "persisted association to this snapshot's complete source inventory. "
        "Snapshot admission, singleton cardinality and matching source fragments "
        "do not establish document/build ownership. Automatic source withheld."
    )


def automatic_source(reader, name, part=1):
    """Called only after a structured legacy miss and reader/doc/session selection."""
    part_number(part)
    if type(name) is not str or not 1 <= len(name) <= 4096 or "\x00" in name:
        raise ValueError("automatic source: invalid name")
    connection = getattr(reader, "_conn", None)
    try:
        snapshot, revision = (
            _snapshot(connection) if connection is not None else (None, None)
        )
    except (ValueError, RuntimeError):
        if part != 1:
            raise ValueError('automatic source: invalid part; total 1') from None
        return _ownership_unknown(reader, None, None) + '\n\n' + COVERAGE_NOTICE
    if snapshot is None:
        return (
            f"Fonte indisponível na busca legada por nome para '{name}'. "
            "A ausência nessa busca não prova ausência de fonte persistida.\n"
            "Source context unknown: selected reader has no admitted binding snapshot.\n\n"
            + COVERAGE_NOTICE
            + " Request direct qualified stored-source evidence via explicit db/snapshot/source_selections."
        )
    ownership_error = _ownership_unknown(reader, snapshot, revision)
    if ownership_error:
        if part != 1:
            raise ValueError("automatic source: invalid part; total 1")
        return (
            f"Fonte indisponível na busca legada por nome para '{name}'.\n"
            + ownership_error
            + "\nRequest direct qualified stored-source evidence via explicit "
            "db/snapshot/source_selections.\n\n" + COVERAGE_NOTICE
        )
    records = _records(snapshot, name, revision)
    from design_graph.interface.mcp.assemble_tool import _code_blocks, _pack

    blocks = []
    for index, record in enumerate(records, 1):
        intro = (
            f"## Automatic lexical source context {index}\n"
            f"snapshot={revision} unit={record['unit']} region={record['region']} "
            f"binding={record['binding']} occurrence={record['occurrence']} UTF-8={record['interval']}\n"
            f"unit_sha256={record['unit_sha256']} source_sha256={record['source_sha256']}\n"
            f"{record['selection']}. IR_ONLY; initialization/value unknown. "
            "Unresolved references and dynamic gaps remain unknown; not complete dependency closure."
        )
        blocks.extend(
            _code_blocks(
                f"Source context {index}", intro, record["source"], record["syntax"]
            )
        )
    pages = _pack(blocks)
    if part > len(pages):
        raise ValueError(f"automatic source: invalid part; total {len(pages)}")
    lines = [
        f"# Automatic lexical source context — parte {part}/{len(pages)}",
        COVERAGE_NOTICE,
    ]
    lines.extend(block.text for block in pages[part - 1])
    if part < len(pages):
        lines.append(
            f"> Continua: get_full(name={name!r}, aspect='source', part={part + 1}) — repeat identical doc/session."
        )
    return "\n".join(lines)
