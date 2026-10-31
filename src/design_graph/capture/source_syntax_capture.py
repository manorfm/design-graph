"""Explicit native producer for the separately versioned syntax envelope."""

import json
from hashlib import sha256
from pathlib import Path

from design_graph.model.binding_capture_ir import (
    BindingCaptureIR,
    CoverageGap,
    FunctionSite,
    binding_id,
)
from design_graph.model.binding_ir import _decode
from design_graph.model.source_syntax import SourceSyntax, SourceSyntaxCapture


def capture_source_syntax(producer, source, *, locator, source_type, syntax, owner_events=None):
    if type(source) is not bytes or len(source) > 1024 * 1024:
        raise ValueError("whole unit must be UTF8 bytes, at most 1 MiB")
    if (
        type(locator) is not str
        or not locator
        or source_type not in ("script", "module")
        or syntax not in ("js", "jsx")
    ):
        raise ValueError("explicit supported source identity required")
    producer._verify_toolchain()
    root = Path(__file__).parents[1]
    pin = json.loads((producer.assets / "source-syntax-pin.json").read_text())
    expected_files = {
        "capture/binding_engine/capture.mjs",
        "capture/binding_engine/source-syntax.mjs",
        "capture/binding_engine/pin.json",
        "capture/binding_capture.py",
        "capture/source_syntax_capture.py",
        "model/source_syntax.py",
        "model/binding_capture_ir.py",
        "model/binding_ir.py",
        "capture/owned_emission.py",
        "capture/owned_html_capture.py",
        "capture/html_prototype/extraction/definition_merge.py",
        "model/source_owner.py",
        "model/entities.py",
    }
    if (
        set(pin) != {"version", "files"}
        or pin["version"] != "source-syntax-producer/1"
        or type(pin["files"]) is not dict
        or set(pin["files"]) != expected_files
    ):
        raise ValueError("unsupported source syntax producer pin")
    for relative, digest in pin["files"].items():
        if sha256((root / relative).read_bytes()).hexdigest() != digest:
            raise ValueError("source syntax producer artifact mismatch: " + relative)
    fingerprint = sha256(
        json.dumps(pin, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    raw = producer._capture_native(
        source.decode("utf8"), source_type, syntax, source_syntax="source-syntax/1"
    )
    ir, intrinsics = producer._inventory(raw, source, locator, source_type, syntax)
    ir = producer._project_references(ir, raw["references"], intrinsics)
    lexical = BindingCaptureIR(
        "binding-capture/3",
        source_type,
        syntax,
        producer.fingerprint,
        ir,
        intrinsics,
        tuple(_decode(CoverageGap, g) for g in raw["gaps"]),
        tuple(_decode(FunctionSite, f) for f in raw["functions"]),
    )
    facts = raw["source_syntax"]
    for alias in facts["aliases"]:
        alias["binding"] = binding_id(ir.units[0].id, *alias.pop("native_binding"))
    facts["unit"] = ir.units[0].id
    result = SourceSyntaxCapture(
        "source-syntax-capture/1", fingerprint, lexical, _decode(SourceSyntax, facts)
    )
    result.check()
    if owner_events is not None:
        owner_events.extend(raw['ownerSources'])
    return result
