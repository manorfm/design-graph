"""Invocation-local BUILD-owned source candidates, never runtime dependency closure."""
from __future__ import annotations

import json
from dataclasses import asdict
from hashlib import sha256

from design_graph.interface.mcp.automatic_source_tool import (
    MAX_CONTEXTS,
    MAX_REFERENCES,
    _context,
    _declaration,
)
from design_graph.interface.mcp.qualified_source_tool import MAX_SOURCE_BYTES
from design_graph.model.graph.binding_context import _rollback, _rows
from design_graph.model.graph.source_build_ownership import _read_source_build_facts
from design_graph.model.source_syntax import _project_admitted_candidates

NOTICE = (
    "BUILD field ownership admitted; native lexical source candidates only. "
    "runtime_claim=false; source closure incomplete/unknown. Initialization, alias "
    "reassignment, global mutations, execution order and unknown scripts remain uncertain."
)
MAX_USES = 1024


def _within(regions, region, owner):
    """Use native parent identities, not a coincident source-span join."""
    seen = set()
    while region is not None and region not in seen:
        if region == owner:
            return True
        seen.add(region)
        region = regions[region].parent
    return False


def _field(connection, name):
    # Match the normal reader's Component-before-Screen selection, retaining its
    # exact table/key identity rather than rediscovering ownership from bytes.
    for table in ('Component', 'Screen'):
        rows = _rows(connection, 'MATCH (n:' + table + ') WHERE n.name=$name RETURN n.source_code', {'name': name})
        if len(rows) == 1 and rows[0][0]:
            return table, json.dumps([name], ensure_ascii=True, sort_keys=True, separators=(',', ':')), rows[0][0]
        if len(rows) > 1:
            raise ValueError('ambiguous selected source field')
    return None


def _contexts(capture, binding, revision):
    bindings = {b.id: b for b in capture.ir.bindings}
    resolutions = {r.id: r for r in capture.ir.resolutions}
    environments = {e.id: e for e in capture.ir.environments}
    queue = [binding]
    seen = set()
    records = []
    if len(capture.ir.references) > MAX_REFERENCES:
        raise ValueError('automatic source reference budget exceeded')
    while queue:
        target = queue.pop(0)
        if target.id in seen or not target.occurrences:
            continue
        seen.add(target.id)
        declaration = _declaration(capture, target)
        if any(r['interval'][0] <= declaration.start < declaration.end <= r['interval'][1] for r in records):
            continue
        function = declaration.kind.value == 'function'
        record = _context(capture, target, revision, function=function)
        if not function:
            record['region'] = environments[declaration.environment].owner
            record['selection'] += '; region is enclosing native scope, NOT exact declaration owner'
        records.append(record)
        if len(records) > MAX_CONTEXTS:
            raise ValueError('automatic source context budget exceeded')
        if function:
            for ref in capture.ir.references:
                if record['interval'][0] <= ref.start < ref.end <= record['interval'][1]:
                    resolution = resolutions[ref.id]
                    if resolution.state.value == 'resolved' and resolution.target in bindings:
                        queue.append(bindings[resolution.target])
    return records


def _select(facts, fields):
    value = facts.value
    captures = {c.source_syntax.unit: c for c in value.syntax.captures}
    witnesses = {(w.table, w.key, w.field): w for w in value.witnesses}
    records = {}
    selections = []
    statuses = {'source-candidate': 0, 'ambiguous': 0, 'unresolved': 0}
    use_count = 0
    for table, key, payload in fields:
        witness = witnesses.get((table, key, 'source_code'))
        if witness is None or witness.mapping != 'exact-slice' or len(witness.origins) != 1:
            continue  # Unsupported/mixed/legacy fields never seed candidates.
        if sha256(payload.encode()).hexdigest() != witness.payload_sha256:
            raise ValueError('stale selected field')
        origin = witness.origins[0]
        consumer = captures[origin.unit]
        refs = {r.id: r for r in consumer.lexical.ir.references}
        regions = {r.id: r for r in consumer.lexical.ir.regions}
        for use in consumer.source_syntax.uses:
            if not _within(regions, refs[use.object_reference].region, origin.native_region):
                continue
            use_count += 1
            if use_count > MAX_USES:
                raise ValueError('automatic source member-use budget exceeded')
            selection = _project_admitted_candidates(value.syntax.scope, value.syntax.captures, origin.unit, use.id)
            # Unknown uses are counted, not expanded into an unbounded prose block.
            statuses[selection.status] += 1
            if selection.status != 'unresolved':
                selections.append({'owner': asdict(witness), 'selection': asdict(selection)})
            if selection.status != 'source-candidate' or len(selection.candidates) != 1:
                continue
            candidate = selection.candidates[0]
            provider = captures[candidate.provider_unit].lexical
            binding = next(b for b in provider.ir.bindings if b.id == candidate.binding)
            try:
                selected = _contexts(provider, binding, value.lexical_snapshot)
            except ValueError:
                continue  # No guessed declaration extent/whole-unit fallback.
            for record in selected:
                identity = (record['snapshot'], record['unit'], record['region'], tuple(record['interval']), record['source_sha256'])
                records.setdefault(identity, record)
    if len(records) > MAX_CONTEXTS or sum(len(r['source'].encode()) for r in records.values()) > MAX_SOURCE_BYTES:
        raise ValueError('automatic source aggregate budget exceeded')
    selections.append({'selected_fields': len(fields), 'native_member_use_status_counts': statuses, 'runtime_claim': False})
    return list(records.values()), selections


def candidate_blocks(reader, names):
    """One private full admission per request; no handle escapes or persists."""
    from design_graph.interface.mcp.assemble_tool import _code_blocks

    if getattr(reader, '_state_path', None) is None:
        return []
    try:
        reader._conn.execute('BEGIN TRANSACTION READ ONLY').close()
        try:
            facts = _read_source_build_facts(reader)
            fields = [_field(reader._conn, name) for name in dict.fromkeys(names)]
            records, selections = _select(facts, [f for f in fields if f is not None])
            reader._conn.execute('COMMIT').close()
        except Exception:
            _rollback(reader._conn)
            raise
    except (ValueError, OSError, RuntimeError, KeyError, TypeError):
        # Preserve useful legacy output. Failed ownership never discloses bytes.
        return []
    if not records:
        return []
    blocks = _code_blocks('Native candidate coverage', '## Native candidate coverage\n' + NOTICE, json.dumps(selections, ensure_ascii=True, sort_keys=True), 'json')
    for index, record in enumerate(records, 1):
        intro = (f"## Automatic source candidate {index}\n{NOTICE}\n"
                 f"snapshot={record['snapshot']} unit={record['unit']} region={record['region']} "
                 f"binding={record['binding']} occurrence={record['occurrence']} UTF-8={record['interval']}\n"
                 f"unit_sha256={record['unit_sha256']} source_sha256={record['source_sha256']}\n{record['selection']}")
        blocks.extend(_code_blocks(f'Native source candidate {index}', intro, record['source'], record['syntax']))
    return blocks


def render_source(reader, name, source, part):
    """Return None for unchanged legacy formatting; never inspect rendered prose."""
    from design_graph.interface.mcp.assemble_tool import _code_blocks, _pack
    from design_graph.interface.mcp.qualified_source_tool import part_number

    part_number(part)
    supplements = candidate_blocks(reader, [name])
    if not supplements:
        return None
    blocks = _code_blocks('Stored source', f'# Fonte completo de {name} ({source["source_lang"]})', source['source_code'], source['source_lang'])
    pages = _pack(blocks + supplements)
    if part > len(pages):
        raise ValueError(f'invalid automatic source part: total {len(pages)}')
    lines = [f'# Automatic stored source — parte {part}/{len(pages)}', NOTICE]
    lines += [b.text for b in pages[part - 1]]
    if part < len(pages):
        lines.append(f'> Continua: get_full(name={name!r}, aspect="source", part={part + 1}) — repeat identical doc/session.')
    return '\n'.join(lines)
