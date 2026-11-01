"""Explicit stored-source evidence; never infer a function value from an owner name.

Qualified assembly reads legacy and binding evidence from the SAME read-only DB.
IR admission checks consistency, not source-to-IR authenticity. A caller's inline
receipt can check retained-byte fidelity, but is not a signature or a file lookup.
"""

from __future__ import annotations

import re
from hashlib import sha256
from pathlib import Path

MAX_SELECTIONS = 16
MAX_SOURCE_BYTES = 512 * 1024
MAX_SELECTOR_CHARS = 4096
QUALIFIED_KEYS = frozenset({"db", "snapshot", "source_selections", "expected_sha256"})
FALSE_COMPLETENESS = "Tudo o que a tela usa está acima — nada foi cortado."
COVERAGE_NOTICE = (
    "Source closure incomplete/unknown: automatic name/member resolution is unsupported; "
    "lexical bindings do not prove K/window.V6K member values, execution order or "
    "cross-unit linkage. Explicit selected supplements are not automatically proved dependencies. "
    "Legacy graph-to-binding snapshot correspondence is not certified."
)

_DIGEST = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_INTERVAL = {"type": "array", "items": {"type": "integer", "minimum": 0},
             "minItems": 2, "maxItems": 2}
_SELECTOR = {"type": "string", "minLength": 1, "maxLength": MAX_SELECTOR_CHARS}
QUALIFIED_PROPERTIES = {
    "db": {**_SELECTOR, "description": "Explicit existing absolute local DB; read-only, 128MiB/two threads. No doc/session mixing."},
    "snapshot": {**_DIGEST, "description": "Exact persisted snapshot revision; no latest/name fallback."},
    "expected_sha256": {**_DIGEST, "description": "Optional independently retained snapshot digest; not a same-DB authentication claim."},
    "source_selections": {
        "type": "array", "minItems": 1, "maxItems": MAX_SELECTIONS,
        "description": (
            "Explicit selected supplements, NOT inferred dependencies. Exact unit/region required. "
            "Omit interval for the entire checked region. A subinterval requires the unit root "
            "region and an inline retained receipt with exact unit/body hashes and interval. "
            "No arbitrary receipt paths. Initializer text is syntax only; initialization/value unknown."
        ),
        "items": {
            "type": "object", "required": ["unit", "region"], "additionalProperties": False,
            "properties": {
                "mode": {"type": "string", "enum": ["region", "retained-interval"],
                         "description": "Default region requires exact region bounds; retained-interval explicitly selects root-contained receipt bytes, not a declaration/body proof."},
                "unit": _SELECTOR, "region": _SELECTOR, "interval": _INTERVAL,
                "receipt": {
                    "type": "object", "additionalProperties": False,
                    "required": ["unit_sha256", "source_sha256", "interval"],
                    "properties": {"unit_sha256": _DIGEST, "source_sha256": _DIGEST, "interval": _INTERVAL},
                },
            },
        },
    },
}


def honest_coverage(text: str) -> str:
    """Correct only the exact terminal standalone completeness footer.

    Compatibility for prose-only callers; product assembly uses structured blocks
    below, never this function on source-bearing documents.
    """
    footer = "\n## 8. Completude\n" + FALSE_COMPLETENESS
    if text.endswith(footer):
        return text[:-len(FALSE_COMPLETENESS)] + COVERAGE_NOTICE
    return text


def _assembly_parts(assembly, known, supplements=(), coverage=COVERAGE_NOTICE):
    """Correct generated metadata before packing; code block text is opaque."""
    from design_graph.interface.mcp.assemble_tool import (
        _Block,
        _blocks,
        _code_blocks,
        _completeness_lines,
        _pack,
    )

    components = [c for c in assembly["components"] if c["name"] not in known]
    omitted = [c["name"] for c in assembly["components"] if c["name"] in known]
    data_part = None
    parts = []
    for _ in range(3):
        blocks = _blocks(assembly, known, data_part)
        assert [b.title for b in blocks[-5:]] == [
            "4. Dados", "5. Comportamento", "6. Tokens", "7. Dependências", "8. Completude",
        ]
        # The baseline generator owns these positions: the final five blocks
        # are data/behaviour/tokens/dependencies/completeness, never source.
        # No source title or Markdown delimiter is interpreted as metadata.
        blocks[-1] = _Block("8. Completude", "\n".join([
            "## 8. Completude", coverage,
            *_completeness_lines(assembly["name"], omitted)[1:], "",
        ]))
        if not assembly["data"] and not assembly["unread_lists"]:
            blocks[-5] = _Block("4. Dados", "## 4. Dados\nNenhum dado repetido registrado; cobertura não provada.\n")
        if not any(o.get("states") or o.get("actions") for o in [assembly, *assembly["components"]]):
            blocks[-4] = _Block("5. Comportamento", "## 5. Comportamento\nNenhum estado nem ação registrado; cobertura não provada.\n")
        if not assembly["tokens"]:
            blocks[-3] = _Block("6. Tokens", "## 6. Tokens usados, por modo\nNenhum token registrado ligado aos componentes; cobertura não provada.\n")
        if not components:
            index = 1 + len(_code_blocks("2. Esqueleto", "## 2. Esqueleto", assembly["skeleton"], assembly["source_lang"]))
            blocks[index] = _Block("3. Componentes", "## 3. Componentes\nNenhum componente adicional registrado; cobertura não provada.\n")
        parts = _pack(blocks + list(supplements))
        found = next(n for n, page in enumerate(parts, 1) if any(b is blocks[-5] for b in page))
        if found == data_part:
            return parts
        data_part = found
    return parts


def assemble_with_coverage(reader, name, known=None, part=1):
    """Legacy assembly with generated claims corrected before source rendering."""
    from design_graph.interface.mcp.assemble_tool import _names, _part_number

    part_number(part)
    assembly = reader.get_screen_assembly(name)
    if not assembly:
        return f"Tela '{name}' não encontrada. Use list_screens() para ver as telas do protótipo."
    names = _names(known)
    from design_graph.interface.mcp.source_candidate_assembly import (
        NOTICE,
        candidate_blocks,
    )

    supplements = candidate_blocks(reader, [assembly['name'], *(c['name'] for c in assembly['components'])])
    parts = _assembly_parts(assembly, names, supplements, NOTICE if supplements else COVERAGE_NOTICE)
    number = _part_number(part, len(parts))
    if number is None:
        return f"Parte inválida: {part!r}. A montagem de '{assembly['name']}' tem as partes 1 a {len(parts)}."
    heading = f"# Montar: {assembly['name']}"
    lines = [heading if len(parts) == 1 else f"{heading} — parte {number}/{len(parts)}", ""]
    if len(parts) > 1 and number == 1:
        lines += ["### Partes", *(f"- Parte {n}: {', '.join(b.title for b in page)}" for n, page in enumerate(parts, 1)), ""]
    lines += [b.text for b in parts[number - 1]]
    if number < len(parts):
        same_known = " — com o mesmo known" if names else ""
        lines.append(f"> Continua: assemble_page('{assembly['name']}', part={number + 1}){same_known}")
    return "\n".join(lines)


def _string(value, field):
    if type(value) is not str or not 1 <= len(value) <= MAX_SELECTOR_CHARS or "\x00" in value:
        raise ValueError(f"invalid qualified source {field}")
    return value


def _digest(value, field):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"invalid qualified source {field} digest")


def _interval(value):
    if (type(value) is not list or len(value) != 2
            or any(type(n) is not int for n in value) or not 0 <= value[0] < value[1]):
        raise ValueError("invalid qualified source interval")
    return tuple(value)


def _selection(value):
    if type(value) is not dict or not {"unit", "region"} <= value.keys() <= {
        "unit", "region", "interval", "receipt", "mode"
    }:
        raise ValueError("invalid qualified source selection fields")
    _string(value["unit"], "unit")
    _string(value["region"], "region")
    if value.get("mode", "region") not in ("region", "retained-interval"):
        raise ValueError("invalid qualified source mode")
    if value.get("mode") == "retained-interval" and not {"interval", "receipt"} <= value.keys():
        raise ValueError("retained-interval mode requires interval and receipt")
    if "interval" in value:
        _interval(value["interval"])
    if "receipt" in value:
        receipt = value["receipt"]
        if type(receipt) is not dict or receipt.keys() != {"unit_sha256", "source_sha256", "interval"}:
            raise ValueError("invalid qualified source receipt fields; no path lookups")
        _digest(receipt["unit_sha256"], "receipt unit")
        _digest(receipt["source_sha256"], "receipt source")
        _interval(receipt["interval"])


def part_number(value):
    if type(value) is not int or value < 1:
        raise ValueError("invalid qualified source part: require positive integer")
    return value


def _arguments(tool, args):
    allowed = QUALIFIED_KEYS | {"name", "part"}
    allowed |= {"aspect"} if tool == "get_full" else {"known"}
    if not {"db", "snapshot", "source_selections"} <= args.keys() <= allowed:
        raise ValueError("qualified source requires db/snapshot/source_selections; no doc/session or partial fallback")
    path = Path(_string(args["db"], "db"))
    if not path.is_absolute():
        raise ValueError("qualified source db must be absolute")
    _digest(args["snapshot"], "snapshot")
    if "expected_sha256" in args:
        _digest(args["expected_sha256"], "external snapshot")
    selections = args["source_selections"]
    if type(selections) is not list or not 1 <= len(selections) <= MAX_SELECTIONS:
        raise ValueError("invalid qualified source selection budget")
    for selection in selections:
        _selection(selection)
    part_number(args.get("part", 1))
    if "name" in args:
        _string(args["name"], "name (label only for source)")
    if tool == "get_full" and args.get("aspect") != "source":
        raise ValueError("qualified source only supports get_full aspect=source")
    if tool == "assemble_page":
        _string(args.get("name"), "exact screen name")
        known = args.get("known", [])
        if type(known) is not list or len(known) > 1000:
            raise ValueError("invalid qualified assembly known budget")
        for name in known:
            _string(name, "known")
    if not path.is_file():
        raise ValueError("qualified source db must be an existing file")
    return path


def _source_record(snapshot, revision, selection):
    """Called only after full persisted snapshot admission; no occurrence slicing."""
    captures = [c for c in snapshot.captures if c.ir.units[0].id == selection["unit"]]
    if len(captures) != 1:
        raise ValueError("missing or ambiguous qualified source unit")
    capture = captures[0]
    unit = capture.ir.units[0]
    regions = [r for r in capture.ir.regions if r.id == selection["region"] and r.unit == unit.id]
    if len(regions) != 1:
        raise ValueError("missing or ambiguous qualified source region")
    region = regions[0]
    raw = unit.source.encode("utf-8")
    if len(raw) != unit.byte_length or sha256(raw).hexdigest() != unit.source_sha256:
        raise ValueError("qualified stored source length/hash mismatch")
    start, end = _interval(selection.get("interval", [region.start, region.end]))
    exact_region = (start, end) == (region.start, region.end)
    if selection.get("mode", "region") == "region" and not exact_region:
        raise ValueError("source interval must equal exact qualified region")
    if selection.get("mode") == "retained-interval" and (region.id != unit.root_region or "receipt" not in selection):
        raise ValueError("retained interval requires exact unit root region and receipt")
    if not region.start <= start < end <= region.end or end > len(raw):
        raise ValueError("qualified source interval outside region")
    body = raw[start:end]
    if len(body) > MAX_SOURCE_BYTES:
        raise ValueError("qualified source byte budget exceeded")
    try:
        text = body.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError("qualified source interval splits UTF-8") from exc
    receipt = selection.get("receipt")
    if receipt is not None and (
        receipt["unit_sha256"] != unit.source_sha256
        or tuple(receipt["interval"]) != (start, end)
        or receipt["source_sha256"] != sha256(body).hexdigest()
    ):
        raise ValueError("qualified source retained receipt mismatch")
    return {"snapshot": revision, "unit": unit.id, "region": region.id,
            "interval": [start, end], "unit_sha256": unit.source_sha256,
            "source_sha256": sha256(body).hexdigest(), "source": text, "syntax": capture.syntax,
            "fidelity": "matches supplied retained receipt (custody, not authentication)" if receipt
            else "stored bytes/hash only; no independent original receipt",
            "selection": "exact region" if exact_region else "explicit receipt-checked root subinterval"}


def _records(snapshot, revision, selections):
    records = [_source_record(snapshot, revision, s) for s in selections]
    keys = [(r["unit"], tuple(r["interval"])) for r in records]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate qualified source selection")
    if sum(len(r["source"].encode()) for r in records) > MAX_SOURCE_BYTES:
        raise ValueError("qualified source aggregate byte budget exceeded")
    return records


def _source_sections(records):
    from design_graph.interface.mcp.qualified_pagination import Section

    blocks = []
    for index, record in enumerate(records, 1):
        intro = (
            f"## Explicit selected supplement {index} (not a proved dependency)\n"
            f"snapshot={record['snapshot']} unit={record['unit']} region={record['region']} "
            f"UTF-8={record['interval']}\n"
            f"unit_sha256={record['unit_sha256']} source_sha256={record['source_sha256']}\n"
            f"{record['selection']}; {record['fidelity']}.\n"
            "IR_ONLY; initialization/value unknown; original initializer text is syntax only. "
            "Binding-to-body and runtime member/cross-unit linkage not asserted."
        )
        blocks.append(Section(f"Selected source {index}", intro, record["source"], record["syntax"]))
    return blocks


def _qualified_assembly_sections(assembly, known):
    """Generate all metadata facts before packing, keeping source separate.

    List locations name their stable section, not a page guessed by repeated
    repacking. Component inventories and known/omitted semantics are unchanged.
    """
    from design_graph.interface.mcp.assemble_tool import (
        _behaviour_lines,
        _completeness_lines,
        _data_lines,
        _header_lines,
        _token_lines,
    )
    from design_graph.interface.mcp.discovery_tools import resource_lines
    from design_graph.interface.mcp.markdown import props_table_lines
    from design_graph.interface.mcp.qualified_pagination import Section

    components = [c for c in assembly["components"] if c["name"] not in known]
    omitted = [c["name"] for c in assembly["components"] if c["name"] in known]
    sections = [
        Section("1. Cabeçalho", "\n".join(["## 1. Cabeçalho", *_header_lines(assembly, None), ""])),
        Section("2. Esqueleto", "## 2. Esqueleto", assembly["skeleton"], assembly["source_lang"]),
        Section("3. Componentes", "## 3. Componentes\n" + (
            "" if components else "Nenhum componente adicional registrado; cobertura não provada.\n")),
    ]
    for component in components:
        intro = f"### {component['name']}"
        if not component["defined"]:
            sections.append(Section(component["name"], intro + "\nReferenciado, sem definição no protótipo (externo ou de biblioteca).\n"))
            continue
        lines = [intro, f"**Tipo**: {component['comp_type']}"]
        if component["props"]:
            lines += ["", *props_table_lines(component["props"])]
        sections.append(Section(component["name"], "\n".join(lines), component["source_code"], component["source_lang"]))
    data = _data_lines(assembly["data"], assembly["unread_lists"]) if assembly["data"] or assembly["unread_lists"] else ["Nenhum dado repetido registrado; cobertura não provada."]
    behaviour = _behaviour_lines(assembly, components) if any(o.get("states") or o.get("actions") for o in [assembly, *assembly["components"]]) else ["Nenhum estado nem ação registrado; cobertura não provada."]
    tokens = _token_lines(assembly["tokens"]) if assembly["tokens"] else ["Nenhum token registrado ligado aos componentes; cobertura não provada."]
    for title, lines in [
        ("4. Dados", data), ("5. Comportamento", behaviour),
        ("6. Tokens usados, por modo", tokens),
        ("7. Dependências", resource_lines(assembly["resources"], heading="###") or ["Nenhuma registrada."]),
        ("8. Completude", [COVERAGE_NOTICE, *_completeness_lines(assembly["name"], omitted)[1:]]),
    ]:
        sections.append(Section(title, "\n".join(["## " + title, *lines, ""])))
    return sections


def _render(tool, args, records, connection):
    from design_graph.interface.mcp.assemble_tool import _names
    from design_graph.interface.mcp.qualified_pagination import render

    sections = []
    if tool == "assemble_page":
        from design_graph.model.graph.reader import GraphReader

        assembly = GraphReader(connection).get_screen_assembly(args["name"])
        if not assembly or assembly["name"] != args["name"]:
            raise ValueError("qualified assembly requires an exact unambiguous stored screen name")
        sections = _qualified_assembly_sections(assembly, _names(args.get("known")))
    heading = f"# {'Montar: ' + args['name'] if tool == 'assemble_page' else 'Qualified source evidence'}"
    return render(sections + _source_sections(records), heading, COVERAGE_NOTICE, tool, args.get("part", 1))


def qualified_source(tool, args):
    """Normal product dispatch: bounded read-only open, full admission, finally close."""
    path = _arguments(tool, args)
    import kuzu

    from design_graph.model.graph.binding_context import read_binding_context

    database = kuzu.Database(str(path), read_only=True, buffer_pool_size=128 * 1024 * 1024, max_num_threads=2)
    try:
        connection = kuzu.Connection(database)
        try:
            snapshot = read_binding_context(connection, args["snapshot"], expected_sha256=args.get("expected_sha256"))
            if snapshot is None:
                raise ValueError("qualified source unavailable: legacy DB has no admitted binding snapshot")
            records = _records(snapshot, args["snapshot"], args["source_selections"])
            return _render(tool, args, records, connection)
        finally:
            connection.close()
    finally:
        database.close()
