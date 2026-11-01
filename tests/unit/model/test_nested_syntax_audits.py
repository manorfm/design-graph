"""Parser-free identity and hostile-data controls for nested syntax admission."""

import json
import os
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

import pytest

from design_graph.model import binding_ir
from design_graph.model import source_syntax as syntax
from design_graph.model.binding_capture_ir import BindingCaptureIR
from design_graph.model.graph import source_syntax_context as storage
from tests.unit.model.test_syntax_preparation_audits import receipt, snapshot


def positive():
    """Hand-built real member witness with native reference/span consistency."""
    value = snapshot()
    captures = []
    for capture in value.captures:
        lexical = capture.lexical
        ir = lexical.ir
        unit = ir.units[0]
        source = "let x=1;x.key; // é🙂"
        raw = source.encode()
        digest = sha256(raw).hexdigest()
        uid = (
            "u:"
            + sha256(
                json.dumps(
                    [unit.locator, lexical.source_type, lexical.syntax, digest],
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
        )
        unit = replace(
            unit, id=uid, source=source, source_sha256=digest, byte_length=len(raw)
        )
        ir = replace(
            ir,
            units=(unit,),
            environments=tuple(replace(x, unit=uid) for x in ir.environments),
            regions=tuple(replace(x, unit=uid, end=len(raw)) for x in ir.regions),
            occurrences=tuple(replace(x, unit=uid) for x in ir.occurrences),
            bindings=tuple(replace(x, unit=uid) for x in ir.bindings),
            references=tuple(replace(x, unit=uid) for x in ir.references),
            resolutions=tuple(replace(x, unit=uid) for x in ir.resolutions),
        )
        bindings = binding_ir.canonical_bindings(ir.environments, ir.occurrences)
        ir = replace(
            ir,
            bindings=bindings,
            resolutions=tuple(
                replace(x, target=bindings[0].id) for x in ir.resolutions
            ),
        )
        use = syntax.MemberUse(
            "u0", syntax.Span(8, 13), "ref", syntax.Token("key", syntax.Span(10, 13))
        )
        # Exact 30eeaf closed-manifest fingerprint, not the candidate producer pin.
        captures.append(
            replace(
                capture,
                producer_fingerprint="08a10d0aa8a6b3a3fa2da32bafbc7a7afec696645bff843c70547b3dbf04c9e0",
                lexical=replace(lexical, ir=ir),
                source_syntax=replace(capture.source_syntax, unit=uid, uses=(use,)),
            )
        )
    captures = tuple(captures)
    return replace(
        value,
        captures=captures,
        inventory=storage._inventory(captures),
        scope=replace(value.scope, units=tuple(c.source_syntax.unit for c in captures)),
    )


def test_nested_identity_audits_removed_only_after_parent(monkeypatch):
    value = snapshot()
    events = []
    for module, name, label in (
        (storage, "_finite", "parent-finite"),
        (storage, "_validate_typed", "parent-type"),
        (syntax, "_finite", "child-finite"),
        (syntax, "_validate_typed", "child-type"),
    ):
        original = getattr(module, name)

        def observe(*args, original=original, label=label):
            result = original(*args)
            events.append((label, id(args[-1])))
            return result

        monkeypatch.setattr(module, name, observe)
    lexical_check = BindingCaptureIR.check
    semantic_run = syntax._SyntaxChecker.run

    def lexical(item):
        events.append(("lexical", id(item)))
        return lexical_check(item)

    def semantic(checker):
        events.append(("semantic", id(checker.c)))
        return semantic_run(checker)

    monkeypatch.setattr(BindingCaptureIR, "check", lexical)
    monkeypatch.setattr(syntax._SyntaxChecker, "run", semantic)
    for _ in range(2):
        events.clear()
        storage._prepare_syntax(value)
        expected = [("parent-finite", id(value)), ("parent-type", id(value))]
        for c in value.captures:
            expected += [("lexical", id(c.lexical)), ("semantic", id(c))]
        print("identity events", events)
        assert events == expected
    for _ in range(2):
        for c in value.captures:
            events.clear()
            c.check()
            assert events == [
                ("child-finite", id(c)),
                ("child-type", id(c)),
                ("lexical", id(c.lexical)),
                ("semantic", id(c)),
            ]


def test_nonempty_positive_canonical_and_past_fingerprint():
    value = positive()
    admitted = storage._prepare_syntax(value)
    assert all(c.source_syntax.uses for c in value.captures)
    assert all(
        c.producer_fingerprint
        == "08a10d0aa8a6b3a3fa2da32bafbc7a7afec696645bff843c70547b3dbf04c9e0"
        for c in value.captures
    )
    assert storage._decode_syntax(admitted.payload).snapshot == value
    assert admitted.body == storage._json(asdict(value))
    for capture in value.captures:
        assert syntax.SourceSyntaxCapture.from_json(capture.to_json()) == capture
    retained = os.environ.get("DG_RETAINED_POSITIVE")
    if retained:
        old = json.loads(Path(retained).read_text())
        assert storage._decode_syntax(old["payload"]).snapshot == value
        assert old == {
            "body": admitted.body,
            "payload": admitted.payload,
            "digest": admitted.digest,
        }
    if os.environ.get("DG_POSITIVE_OUTPUT"):
        Path(os.environ["DG_POSITIVE_OUTPUT"]).write_text(
            json.dumps(
                {
                    "body": admitted.body,
                    "payload": admitted.payload,
                    "digest": admitted.digest,
                },
                sort_keys=True,
            )
        )


def test_capture_shadow_check_cannot_bypass_real_semantics():
    value = positive()
    last = value.captures[-1]
    use = last.source_syntax.uses[0]
    bad = replace(
        last,
        source_syntax=replace(
            last.source_syntax, uses=(replace(use, key=replace(use.key, name="wrong")),)
        ),
    )
    object.__setattr__(bad, "check", lambda: None)
    with pytest.raises(ValueError, match="anchor"):
        storage._prepare_syntax(replace(value, captures=(value.captures[0], bad)))


def test_last_nonempty_witness_rejected_after_recomputed_digest():
    admitted = storage._prepare_syntax(positive())
    data = json.loads(admitted.payload)
    data["snapshot"]["captures"][-1]["source_syntax"]["uses"][0]["key"]["name"] = (
        "wrong"
    )
    data["sha256"] = sha256(storage._json(data["snapshot"]).encode()).hexdigest()
    with pytest.raises(ValueError, match="anchor"):
        storage._decode_syntax(json.dumps(data))


@pytest.mark.parametrize("kind", ["cycle", "depth", "string", "nodes"])
def test_standalone_finite_preceded_types(kind, monkeypatch):
    capture = snapshot().captures[0]
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

    def refuse(*args):
        raise AssertionError("type traversal preceded finite refusal")

    monkeypatch.setattr(syntax, "_validate_typed", refuse)
    with pytest.raises(ValueError, match="budget"):
        replace(capture, source_syntax=data).check()


def test_generated_body_and_envelope_budgets_retained(monkeypatch):
    from design_graph.model.graph import binding_context

    value = positive()
    body = value._body()
    # A generated body may fit while its distinct envelope exceeds the limit.
    monkeypatch.setattr(binding_context, "MAX_JSON_CHARS", len(body))
    with pytest.raises(ValueError, match="budget"):
        storage._prepare_syntax(value)
    monkeypatch.setattr(binding_context, "MAX_JSON_CHARS", 10)
    object.__setattr__(value, "_body", lambda: " " * 11)
    with pytest.raises(ValueError, match="budget"):
        storage._prepare_syntax(value)


def test_embedded_and_qualified_nonempty_admitted_fresh(monkeypatch):
    from design_graph.model.graph import source_build_ownership as ownership

    value = positive()
    embedded = receipt(value)
    embedded = replace(
        embedded,
        producer=replace(
            embedded.producer, syntax_fingerprint=value.captures[0].producer_fingerprint
        ),
    )
    payload = storage._prepare_syntax(value).payload
    seen = []
    original = storage._validate_typed

    def typed(cls, item):
        result = original(cls, item)
        seen.append(item)
        return result

    monkeypatch.setattr(storage, "_validate_typed", typed)
    decoded = ownership._decode_receipt(embedded.to_json())
    qualified = storage._decode_syntax(payload)
    assert len(seen) == 3
    assert seen[0] is value and seen[1] is decoded.syntax
    assert seen[2] is qualified.snapshot
    assert (
        qualified.snapshot == decoded.syntax
        and qualified.snapshot is not decoded.syntax
    )
    decoded.check()
    assert len(seen) == 4 and seen[-1] is decoded.syntax


@pytest.mark.parametrize(
    "kind",
    [
        "fake",
        "subclass",
        "list",
        "dict",
        "bool-int",
        "enum",
        "string",
        "arity",
        "version",
        "fingerprint",
    ],
)
def test_standalone_public_capture_guards(kind):
    capture = positive().captures[0]
    if kind == "fake":

        class Fake:
            def check(self):
                raise AssertionError("untrusted check")

        bad = Fake()
    elif kind == "subclass":

        class Subclass(syntax.SourceSyntaxCapture):
            pass

        bad = Subclass(
            capture.version,
            capture.producer_fingerprint,
            capture.lexical,
            capture.source_syntax,
        )
    elif kind in ("list", "dict", "arity"):
        use = capture.source_syntax.uses[0]
        uses = (
            [use] if kind == "list" else ({"u0": use} if kind == "dict" else ((use,),))
        )
        bad = replace(capture, source_syntax=replace(capture.source_syntax, uses=uses))
    elif kind == "bool-int":
        use = capture.source_syntax.uses[0]
        bad = replace(
            capture,
            source_syntax=replace(
                capture.source_syntax,
                uses=(replace(use, member_span=syntax.Span(True, 13)),),
            ),
        )
    elif kind == "enum":
        ir = capture.lexical.ir
        ir = replace(ir, references=(replace(ir.references[0], access="read"),))
        bad = replace(capture, lexical=replace(capture.lexical, ir=ir))
    elif kind == "string":
        bad = replace(capture, producer_fingerprint=1)
    elif kind == "version":
        bad = replace(capture, version="unknown")
    else:
        bad = replace(capture, producer_fingerprint="b" * 63)
    with pytest.raises(ValueError):
        syntax.SourceSyntaxCapture.check(bad)
    # The enclosing path has the same exact-type/semantic refusal obligations.
    value = positive()
    with pytest.raises(ValueError):
        storage._prepare_syntax(replace(value, captures=(value.captures[0], bad)))
    capture.check()


def test_standalone_capture_repeated_full_audits(monkeypatch):
    capture = positive().captures[0]
    events = []
    finite, typed = syntax._finite, syntax._validate_typed

    def f(item):
        result = finite(item)
        events.append(("finite", id(item)))
        return result

    def t(cls, item):
        result = typed(cls, item)
        events.append(("typed", id(item)))
        return result

    monkeypatch.setattr(syntax, "_finite", f)
    monkeypatch.setattr(syntax, "_validate_typed", t)
    for _ in range(2):
        events.clear()
        capture.check()
        assert events == [("finite", id(capture)), ("typed", id(capture))]


def test_shadow_snapshot_check_did_not_bypass_prepare():
    value = replace(positive(), version="wrong")
    object.__setattr__(value, "check", lambda: None)
    with pytest.raises(ValueError):
        storage._prepare_syntax(value)


def test_real_nonempty_semantic_order_preserved(monkeypatch):
    value = positive()
    events = []
    lexical_check, semantic_run = BindingCaptureIR.check, syntax._SyntaxChecker.run

    def lexical(item):
        events.append(("lexical", item.ir.units[0].locator))
        return lexical_check(item)

    def semantic(checker):
        events.append(("syntax", checker.unit.locator))
        return semantic_run(checker)

    monkeypatch.setattr(BindingCaptureIR, "check", lexical)
    monkeypatch.setattr(syntax._SyntaxChecker, "run", semantic)
    for _ in range(2):
        events.clear()
        storage._prepare_syntax(value)
        assert events == [
            ("lexical", "pure:first.js"),
            ("syntax", "pure:first.js"),
            ("lexical", "pure:last.js"),
            ("syntax", "pure:last.js"),
        ]
