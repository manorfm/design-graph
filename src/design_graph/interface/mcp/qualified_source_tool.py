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
    """Preserve legacy content except unsupported absence/completeness assertions."""
    replacements = {
        FALSE_COMPLETENESS: COVERAGE_NOTICE,
        "Nenhum além dos que você já tem.": "Nenhum componente adicional registrado; cobertura não provada.",
        "Nenhum dado repetido.": "Nenhum dado repetido registrado; cobertura não provada.",
        "Nenhum estado nem ação nos elementos desta tela.": "Nenhum estado nem ação registrado; cobertura não provada.",
        "Nenhum token ligado aos componentes desta tela.": "Nenhum token registrado ligado aos componentes; cobertura não provada.",
    }
    lines = []
    fence = None
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        marker = re.match(r"^(`{3,}|~{3,})", content)
        if marker and fence is None:
            fence = marker.group(1)
        elif fence is not None:
            if content == fence:
                fence = None
        elif content in replacements:
            line = replacements[content] + line[len(content):]
        lines.append(line)
    return "".join(lines)


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


def _source_blocks(records):
    from design_graph.interface.mcp.assemble_tool import _code_blocks

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
        blocks.extend(_code_blocks(f"Selected source {index}", intro, record["source"], record["syntax"]))
    return blocks


def _render(tool, args, records, connection):
    from design_graph.interface.mcp.assemble_tool import _names, _pack, _packed

    blocks = []
    if tool == "assemble_page":
        from design_graph.model.graph.reader import GraphReader

        assembly = GraphReader(connection).get_screen_assembly(args["name"])
        if not assembly or assembly["name"] != args["name"]:
            raise ValueError("qualified assembly requires an exact unambiguous stored screen name")
        blocks = [b for page in _packed(assembly, _names(args.get("known"))) for b in page]
    parts = _pack(blocks + _source_blocks(records))
    number = args.get("part", 1)
    if number > len(parts):
        raise ValueError(f"invalid qualified source part: total {len(parts)}")
    heading = f"# {'Montar: ' + args['name'] if tool == 'assemble_page' else 'Qualified source evidence'}"
    lines = [f"{heading} — parte {number}/{len(parts)}", COVERAGE_NOTICE]
    if number == 1:
        lines += ["### Partes", *(f"- Parte {n}: {', '.join(b.title for b in page)}"
                                   for n, page in enumerate(parts, 1))]
    lines += [honest_coverage(b.text) for b in parts[number - 1]]
    if number < len(parts):
        lines.append(f"> Continua: {tool}(part={number + 1}) — repeat identical db/snapshot/source_selections/name/known/aspect arguments.")
    return "\n".join(lines)


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
