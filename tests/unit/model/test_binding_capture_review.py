import json
import os
from pathlib import Path

import pytest

from design_graph.capture.binding_capture import BindingCapture
from design_graph.model.binding_capture_ir import BindingCaptureIR

FP = os.environ["DG_CAPTURE_FINGERPRINT"]


def provider():
    return BindingCapture(
        node=Path(os.environ["DG_CAPTURE_NODE"]),
        toolchain=Path(os.environ["DG_CAPTURE_ENGINE"]),
        fingerprint=FP,
    )


@pytest.fixture(scope="module")
def p():
    return provider()


def cap(p, s, mode="script", locator="review.js"):
    return p.capture(s.encode(), locator=locator, source_type=mode, syntax="js")


def marked(c, m):
    raw = c.ir.units[0].source.encode()
    pos = raw.index(("/*" + m + "*/").encode()) + len(m) + 4
    r = next(r for r in c.ir.references if r.start == pos)
    z = next(z for z in c.check().resolutions if z.id == r.id)
    b = next((b for b in c.ir.bindings if b.id == z.target), None)
    return z, [
        (d.start, d.end, d.kind.value)
        for d in c.ir.occurrences
        if b and d.id in b.occurrences
    ]


def test_blocker_annex_b_switch_gap(p):
    c = cap(
        p,
        "let X;function bad(){switch(0){case 0:function X(){}}return /*r*/X;}function good(){return /*g*/X;}",
    )
    assert marked(c, "g")[0].state.value == "resolved"
    assert marked(c, "r")[0].state.value == "unknown", (
        "Annex B CaseClause function incorrectly targets outer let without gap"
    )


def test_blocker_shadowed_eval_intrinsic_possible(p):
    c = cap(
        p,
        'let X;function bad(eval){eval("var X=1");return /*r*/X;}function good(){return /*g*/X;}',
    )
    assert marked(c, "g")[0].state.value == "resolved"
    assert marked(c, "r")[0].state.value == "unknown", (
        "bad(globalThis.eval) is legal direct eval; resolved parameter is not proof of non-intrinsic value"
    )


def test_body_class_lexical_positive(p):
    c = cap(p, "function f(){class X {m(){return /*i*/X;}}return /*o*/X;}", "module")
    assert marked(c, "i")[0].target != marked(c, "o")[0].target
    assert marked(c, "i")[1] == marked(c, "o")[1] == [(19, 20, "class")]


def test_independent_exact_default_switch_lookup(p):
    s = "const X=1;function f(p=()=>/*d*/X){function X(){}var X;switch(/*s*/X){case /*t*/X:let X;return /*b*/X;}}"
    c = cap(p, s, "module")
    expected = {
        "d": [(6, 7, "const")],
        "s": [(41, 42, "function"), (50, 51, "var")],
        "t": [(80, 81, "let")],
        "b": [(80, 81, "let")],
    }
    # Compute oracle positions from explicit source tokens, independent of producer records.
    expected["s"] = [
        (s.index("function X") + 9, s.index("function X") + 10, "function"),
        (s.index("var X") + 4, s.index("var X") + 5, "var"),
    ]
    expected["t"] = expected["b"] = [
        (s.index("let X") + 4, s.index("let X") + 5, "let")
    ]
    for m, x in expected.items():
        assert marked(c, m)[1] == x
    assert (
        marked(c, "d")[0].target != marked(c, "s")[0].target != marked(c, "b")[0].target
    )


@pytest.mark.parametrize(
    "source",
    [
        'let X;function f(){eval("var X=1");return /*r*/X;}function g(){return /*g*/X;}',
        "let X;function f(o){with(o){return ()=>/*r*/X;}}function g(){return /*g*/X;}",
        "let X;function f(){{function X(){}}return /*r*/X;}function g(){return /*g*/X;}",
    ],
)
def test_localized_actual_dynamic_controls(p, source):
    c = cap(p, source)
    assert marked(c, "r")[0].state.value == "unknown"
    assert marked(c, "g")[0].state.value == "resolved"


def test_strict_eval_is_not_dynamic_binding_gap(p):
    c = cap(p, '"use strict";let X;function f(){eval("var X=1");return /*r*/X;}')
    assert not c.gaps and marked(c, "r")[1] == [(17, 18, "let")]


def test_source_qualified_id_and_duplicate_occurrences(p):
    s = "var X;function X(){}function f(){return /*r*/X;}"
    a, b = cap(p, s, locator="a.js"), cap(p, s, locator="b.js")
    assert marked(a, "r")[0].target != marked(b, "r")[0].target
    assert (
        marked(a, "r")[1] == marked(b, "r")[1] == [(4, 5, "var"), (15, 16, "function")]
    )


def test_implicit_arguments_and_real_name_cells(p):
    s = "function f(p=()=>/*d*/arguments){var arguments;return /*b*/arguments;}"
    c = cap(p, s, "module")
    assert marked(c, "d")[1] == []
    assert marked(c, "b")[1] == [(37, 46, "var")]
    assert marked(c, "d")[0].target != marked(c, "b")[0].target
    s = "const f=function Named(){return /*r*/Named;};"
    c = cap(p, s, "module")
    assert marked(c, "r")[1] == [(17, 22, "function-name")]


def test_escape_astral_crlf_exact_bytes(p):
    s = "const \\u0058=1;/* 😀 */\r\nfunction f(p=()=>/*r*/X){return /*b*/X;}"
    c = cap(p, s, "module")
    assert c.ir.units[0].source.encode() == s.encode()
    assert marked(c, "r")[1] == [(6, 12, "const")]
    assert marked(c, "r")[0].target == marked(c, "b")[0].target
    s = "const 𐐀=1;function f(){return /*r*/𐐀;}"
    assert marked(cap(p, s), "r")[1] == [(6, 10, "const")]


def test_capture_cannot_execute_source(p, tmp_path):
    sentinel = tmp_path / "SOURCE_WAS_EXECUTED"
    s = 'throw Error("do not execute");process.exit(17);const X=1;/*r*/X;'
    c = cap(p, s)
    assert marked(c, "r")[1] == [
        (s.index("const X") + 6, s.index("const X") + 7, "const")
    ]
    assert not sentinel.exists()


def test_ambient_nodeoptions_not_forwarded(monkeypatch, tmp_path):
    monkeypatch.setenv("NODE_OPTIONS", "--require=" + str(tmp_path / "NONEXISTENT.cjs"))
    monkeypatch.setenv("NODE_PATH", str(tmp_path / "NONEXISTENT"))
    p = provider()
    assert "NODE_OPTIONS" not in p.env and "NODE_PATH" not in p.env
    assert cap(p, "let X;/*r*/X;").check().evidence.value == "ir-only"


@pytest.mark.parametrize(
    "source", [b"x" * (1024 * 1024 + 1), bytearray(b"let X;"), b"\xff"]
)
def test_source_input_bounds_fail_closed(p, source):
    with pytest.raises((ValueError, UnicodeError)):
        p.capture(source, locator="x.js", source_type="script", syntax="js")


def test_untrusted_payload_structure_bounds(p):
    c = cap(p, "let X;/*r*/X;")
    mutations = []
    x = json.loads(c.to_json())
    x["ir"]["references"][0]["start"] = -1
    mutations.append(x)
    x = json.loads(c.to_json())
    x["ir"]["references"][0]["unit"] = "elsewhere"
    mutations.append(x)
    x = json.loads(c.to_json())
    x["ir"]["regions"][0]["start"] = False
    mutations.append(x)
    x = json.loads(c.to_json())
    x["ir"]["regions"][0]["parent"] = "r0"
    mutations.append(x)
    x = json.loads(c.to_json())
    x["ir"]["units"][0]["source_sha256"] = "0" * 64
    mutations.append(x)
    for x in mutations:
        with pytest.raises(ValueError):
            BindingCaptureIR.from_json(json.dumps(x))
    with pytest.raises(ValueError):
        BindingCaptureIR.from_json(
            c.to_json().replace(
                '"version":"binding-capture/2"',
                '"version":"binding-capture/2","version":"binding-capture/2"',
            )
        )


def test_fingerprint_is_not_attestation(p):
    c = cap(p, "let X;/*r*/X;")
    x = json.loads(c.to_json())
    x["engine_fingerprint"] = "0" * 64
    assert BindingCaptureIR.from_json(json.dumps(x)).check().evidence.value == "ir-only"
    with pytest.raises(TypeError):
        BindingCapture(
            node=Path(os.environ["DG_CAPTURE_NODE"]),
            toolchain=Path(os.environ["DG_CAPTURE_ENGINE"]),
        )
