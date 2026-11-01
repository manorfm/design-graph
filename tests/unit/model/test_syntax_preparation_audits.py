"""Pure typed fixtures: no parser, capture, subprocess or database admission."""

import json
import os
from collections import Counter
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

import pytest

from design_graph.model import binding_ir as ir
from design_graph.model import source_syntax as syntax
from design_graph.model.binding_capture_ir import BindingCaptureIR
from design_graph.model.graph import source_syntax_context as storage


def snapshot():
    captures = []
    for locator in ("pure:first.js", "pure:last.js"):
        source = "let x=1;x; // é🙂"
        raw = source.encode()
        source_hash = sha256(raw).hexdigest()
        unit_id = (
            "u:"
            + sha256(
                json.dumps(
                    [locator, "script", "js", source_hash], separators=(",", ":")
                ).encode()
            ).hexdigest()
        )
        unit = ir.SourceUnit(unit_id, locator, source, source_hash, len(raw), "root")
        env = ir.Environment(
            "env", unit_id, ir.EnvironmentKind.ROOT, "root", None, True
        )
        root = ir.EvaluationRegion(
            "root",
            unit_id,
            ir.EvaluationSlot.ROOT,
            None,
            "env",
            0,
            len(raw),
            None,
            True,
        )
        declaration = ir.DeclarationOccurrence(
            "d", unit_id, "env", ir.Namespace.VALUE, "x", ir.DeclarationKind.LET, 4, 5
        )
        bindings = ir.canonical_bindings((env,), (declaration,))
        ref = ir.Reference(
            "ref", unit_id, "root", ir.Namespace.VALUE, "x", ir.AccessKind.READ, 8, 9
        )
        resolution = ir.Resolution(
            "ref", unit_id, ir.ResolutionState.RESOLVED, "env", bindings[0].id, ("env",)
        )
        envelope = ir.Envelope(
            "binding-ir/3",
            "static-unit-chain/3",
            (unit,),
            (env,),
            (root,),
            (declaration,),
            bindings,
            (ref,),
            (resolution,),
        )
        lexical = BindingCaptureIR(
            "binding-capture/3", "script", "js", "a" * 64, envelope, (), (), ()
        )
        captures.append(
            syntax.SourceSyntaxCapture(
                "source-syntax-capture/1",
                "b" * 64,
                lexical,
                syntax.SourceSyntax("source-syntax/1", unit_id, (), (), (), ()),
            )
        )
    captures = tuple(captures)
    scope = syntax.SourceInventory(
        "c" * 64, "pure:constructed", tuple(c.source_syntax.unit for c in captures)
    )
    return storage.SourceSyntaxSnapshot(
        storage.LOGICAL_VERSION, scope, storage._inventory(captures), captures
    )


def test_preparation_audited_snapshot_once_per_independent_invocation(monkeypatch):
    value = snapshot()
    counts = Counter()
    finite, typed = storage._finite, storage._validate_typed

    def observe_finite(item):
        if type(item) is storage.SourceSyntaxSnapshot:
            counts["finite"] += 1
        return finite(item)

    def observe_typed(cls, item):
        if cls is storage.SourceSyntaxSnapshot:
            counts["typed"] += 1
        return typed(cls, item)

    monkeypatch.setattr(storage, "_finite", observe_finite)
    monkeypatch.setattr(storage, "_validate_typed", observe_typed)
    first = storage._prepare_syntax(value)
    observed = dict(counts)
    print("snapshot-wide audits per preparation:", observed)
    assert observed == {"finite": 1, "typed": 1}
    assert storage._prepare_syntax(value) == first
    assert counts == {"finite": 2, "typed": 2}
    qualified = storage._decode_syntax(first.payload)
    assert qualified.snapshot == value and qualified.snapshot is not value
    assert counts == {"finite": 3, "typed": 3}, (
        "qualified copy must be independently admitted"
    )


def test_canonical_bytes_matched_exact_parent_and_roundtrip():
    value = snapshot()
    admitted = storage._prepare_syntax(value)
    assert storage._decode_syntax(admitted.payload).snapshot == value
    assert admitted.body == storage._json(asdict(value))
    assert admitted.digest == sha256(admitted.body.encode()).hexdigest()
    evidence = os.environ.get("DG_CANONICAL_OUTPUT")
    if evidence:
        Path(evidence).write_text(
            json.dumps(
                {
                    "body": admitted.body,
                    "payload": admitted.payload,
                    "digest": admitted.digest,
                },
                sort_keys=True,
            )
        )


def receipt(value):
    """Synthetic consistency input, never a BUILD or database ownership proof."""
    from design_graph.model.graph import schema
    from design_graph.model.graph import source_build_ownership as ownership

    tables = tuple(
        ownership.TableCommitment(ddl.split("(", 1)[0].split()[-1], ddl, 0, "d" * 64)
        for ddl in schema.SCHEMA
    )
    inputs = tuple(
        ownership.InputUnit(
            c.lexical.ir.units[0].locator,
            c.lexical.ir.units[0].source_sha256,
            c.lexical.ir.units[0].byte_length,
            c.lexical.source_type,
            c.lexical.syntax,
        )
        for c in value.captures
    )
    coverage = tuple(
        ownership.CoverageRecord(
            u.locator,
            "captured",
            "text/javascript",
            source_type=u.source_type,
            syntax=u.syntax,
            source_sha256=u.source_sha256,
            byte_length=u.byte_length,
        )
        for u in inputs
    )
    return ownership.SourceBuildOwnership(
        ownership.VERSION,
        ownership.BUILDER,
        ownership.DocumentDomain("pure:document", ("Pure",)),
        value.scope.input_artifact,
        "d" * 64,
        sum(u.byte_length for u in inputs),
        inputs,
        coverage,
        ownership.ProducerIdentity(
            "a" * 64, "b" * 64, (ownership.ArtifactPin("pure:producer", "d" * 64),)
        ),
        value.scope.snapshot,
        "e" * 64,
        ownership.GeneralCommitment(
            "binding-general-properties/1",
            schema.MODEL_VERSION,
            "html_prototype",
            "d" * 64,
            tables,
        ),
        (),
        storage._prepare_syntax(value).digest,
        value,
    )


def test_embedded_receipt_and_qualified_copy_admitted_independently(monkeypatch):
    from design_graph.model.graph import source_build_ownership as ownership

    value = snapshot()
    embedded = receipt(value)
    transport = storage._prepare_syntax(value).payload
    counts = Counter()
    original = storage._finite

    def observe(item):
        if type(item) is storage.SourceSyntaxSnapshot:
            counts["snapshot"] += 1
        return original(item)

    monkeypatch.setattr(storage, "_finite", observe)
    decoded = ownership._decode_receipt(embedded.to_json())
    assert decoded == embedded
    assert counts == {"snapshot": 2}, (
        "receipt serialization and decode are independent preparations"
    )
    qualified = storage._decode_syntax(transport)
    assert qualified.snapshot == decoded.syntax
    assert qualified.snapshot is not decoded.syntax
    assert counts == {"snapshot": 3}
    decoded.check()
    assert counts == {"snapshot": 4}, "no checked object credential survives admission"


def test_exact_tuple_arity_remained_closed():
    ir._validate_typed(tuple[int, str], (1, "ok"))
    for malformed in ((1,), (1, "ok", 3), [1, "ok"]):
        with pytest.raises(ValueError):
            ir._validate_typed(tuple[int, str], malformed)


def test_same_object_was_readmitted_after_in_memory_corruption():
    value = snapshot()
    original = storage._prepare_syntax(value)
    unit = value.captures[-1].lexical.ir.units[0]
    saved = unit.source_sha256
    try:
        object.__setattr__(unit, "source_sha256", "0" * 64)
        with pytest.raises(ValueError):
            storage._prepare_syntax(value)
    finally:
        object.__setattr__(unit, "source_sha256", saved)
    assert storage._prepare_syntax(value) == original


class Permissive:
    def check(self):
        raise AssertionError("untrusted method must not execute")

    def _body(self):
        raise AssertionError("untrusted serialization must not execute")


class SnapshotSubclass(storage.SourceSyntaxSnapshot):
    check = Permissive.check
    _body = Permissive._body


@pytest.mark.parametrize(
    "kind",
    [
        "fake",
        "subclass",
        "list",
        "dict",
        "bool-int",
        "int-bool",
        "string-int",
        "enum",
        "record",
        "hash",
        "resolution",
        "slot",
        "function",
        "gap",
        "syntax",
        "version",
        "units",
        "nested-list",
        "nested-dict",
        "catch-kind",
        "utf8-span",
    ],
)
def test_direct_objects_preserved_exact_types_and_semantics(kind):
    value = snapshot()
    last = value.captures[-1]
    lexical = last.lexical
    envelope = lexical.ir
    if kind == "fake":
        bad = Permissive()
    elif kind == "subclass":
        bad = SnapshotSubclass(
            value.version, value.scope, value.inventory, value.captures
        )
    elif kind == "list":
        bad = replace(value, captures=list(value.captures))
    elif kind == "dict":
        bad = replace(value, scope={"snapshot": value.scope.snapshot})
    elif kind == "record":
        bad = replace(value, scope=Permissive())
    elif kind == "version":
        bad = replace(value, version="unknown")
    elif kind == "units":
        bad = replace(value, scope=replace(value.scope, units=value.scope.units[::-1]))
    else:
        if kind in ("bool-int", "string-int", "hash"):
            unit = envelope.units[0]
            unit = replace(
                unit,
                **(
                    {"source_sha256": "0" * 64}
                    if kind == "hash"
                    else {"byte_length": True if kind == "bool-int" else "1"}
                ),
            )
            envelope = replace(envelope, units=(unit,))
        elif kind in ("int-bool", "enum", "slot"):
            root = envelope.regions[0]
            root = replace(
                root,
                **(
                    {"complete": 1}
                    if kind == "int-bool"
                    else {
                        "slot": "root"
                        if kind == "enum"
                        else ir.EvaluationSlot.CATCH_BODY
                    }
                ),
            )
            envelope = replace(envelope, regions=(root,))
        elif kind == "resolution":
            envelope = replace(
                envelope, resolutions=(replace(envelope.resolutions[0], target=None),)
            )
        elif kind == "function":
            from design_graph.model.binding_capture_ir import FunctionSite

            lexical = replace(lexical, functions=(FunctionSite("root", "ordinary"),))
        elif kind == "gap":
            from design_graph.model.binding_capture_ir import CoverageGap

            lexical = replace(lexical, gaps=(CoverageGap("root", "dynamic-with"),))
        elif kind == "nested-list":
            envelope = replace(envelope, references=list(envelope.references))
        elif kind == "nested-dict":
            envelope = replace(envelope, units=({},))
        elif kind == "catch-kind":
            declaration = replace(
                envelope.occurrences[0], kind=ir.DeclarationKind.PARAMETER
            )
            envelope = replace(envelope, occurrences=(declaration,))
        elif kind == "utf8-span":
            start = envelope.units[0].source.encode().index("é".encode()) + 1
            unsupported = syntax.Unsupported(
                "x0", "computed-or-optional-member", syntax.Span(start, start + 1)
            )
            last = replace(
                last,
                source_syntax=replace(last.source_syntax, unsupported=(unsupported,)),
            )
        elif kind == "syntax":
            last = replace(
                last, source_syntax=replace(last.source_syntax, unit="foreign")
            )
        last = replace(last, lexical=replace(lexical, ir=envelope))
        bad = replace(value, captures=(value.captures[0], last))
    storage._prepare_syntax(value)
    with pytest.raises(ValueError):
        storage._prepare_syntax(bad)
    assert storage._prepare_syntax(value).snapshot == value


@pytest.mark.parametrize("kind", ["cycle", "depth", "string", "nodes"])
def test_finite_limits_preceded_recursive_type_audit(kind, monkeypatch):
    value = snapshot()
    if kind == "cycle":
        data = []
        data.append(data)
    elif kind == "depth":
        data = ()
        for _ in range(syntax.MAX_DEPTH + 1):
            data = (data,)
    elif kind == "string":
        monkeypatch.setattr(syntax, "MAX_CHARS", 20)
        data = "x" * 21
    else:
        monkeypatch.setattr(syntax, "MAX_NODES", 20)
        data = (0,) * 21

    def must_not_recurse(*args):
        raise AssertionError("finite guard must reject before recursive type audit")

    monkeypatch.setattr(storage, "_validate_typed", must_not_recurse)
    with pytest.raises(ValueError, match="budget"):
        storage._prepare_syntax(replace(value, captures=data))


@pytest.mark.parametrize(
    "kind",
    [
        "duplicate",
        "missing",
        "unknown",
        "hash",
        "last",
        "malformed",
        "depth",
        "nonfinite",
        "size",
        "containers",
    ],
)
def test_hostile_transport_and_fresh_readmission(kind, monkeypatch):
    value = snapshot()
    admitted = storage._prepare_syntax(value)
    data = json.loads(admitted.payload)
    if kind == "duplicate":
        text = admitted.payload.replace(
            '{"sha256":', '{"sha256":"' + admitted.digest + '","sha256":', 1
        )
    elif kind in ("missing", "unknown", "hash", "last"):
        if kind == "missing":
            del data["snapshot"]["version"]
        elif kind == "unknown":
            data["snapshot"]["checked"] = True
        elif kind == "hash":
            data["sha256"] = "0" * 64
        else:
            data["snapshot"]["captures"][-1]["lexical"]["ir"]["resolutions"][0][
                "target"
            ] = None
            data["sha256"] = sha256(
                storage._json(data["snapshot"]).encode()
            ).hexdigest()
        text = json.dumps(data)
    elif kind == "depth":
        text = "[" * 100 + "0" + "]" * 100
    elif kind == "nonfinite":
        data["snapshot"]["captures"][-1]["lexical"]["ir"]["units"][0]["byte_length"] = (
            float("nan")
        )
        text = json.dumps(data)
    elif kind == "size":
        text = admitted.payload
        from design_graph.model.graph import binding_context

        monkeypatch.setattr(binding_context, "MAX_JSON_CHARS", 10)
        text = admitted.payload
    elif kind == "containers":
        from design_graph.model.graph import binding_context

        monkeypatch.setattr(binding_context, "MAX_RECORDS", 1)
        text = admitted.payload
    else:
        text = "{"
    with pytest.raises(ValueError):
        storage._decode_syntax(text)
    if kind not in ("size", "containers"):
        assert storage._decode_syntax(admitted.payload).snapshot == value
