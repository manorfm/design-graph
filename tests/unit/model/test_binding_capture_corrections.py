"""Real capture regressions for reviewed semantic gaps; never execute fixture JS."""

import pytest

from .test_binding_capture import provider


def capture(source, mode="script"):
    return provider().capture(
        source.encode(), locator="corrections.js", source_type=mode, syntax="js"
    )


def marked(result, marker):
    source = result.ir.units[0].source.encode()
    offset = source.index(("/*" + marker + "*/").encode()) + len(marker) + 4
    ref = next(r for r in result.ir.references if r.start == offset)
    resolution = next(r for r in result.check().resolutions if r.id == ref.id)
    binding = next((b for b in result.ir.bindings if b.id == resolution.target), None)
    occurrences = [
        (d.start, d.end, d.kind.value)
        for d in result.ir.occurrences
        if binding and d.id in binding.occurrences
    ]
    return resolution, occurrences


ANNEX_POSITIONS = [
    "{function X(){}}",
    "switch(0){case 0:function X(){}}",
    "switch(0){default:function X(){}}",
    "if(1)function X(){}",
    "if(0){}else function X(){}",
    "label:function X(){}",
    "label:other:function X(){}",
    "if(1)label:function X(){}",
    "while(0){function X(){}}",
    "do {function X(){}} while(0);",
    "for(;false;){function X(){}}",
    "{function X(){'use strict';}}",
]


@pytest.mark.parametrize("statement", ANNEX_POSITIONS)
def test_annex_accepted_positions_have_local_gap(statement):
    source = (
        "let X;function bad(p=()=>/*p*/X){"
        "const before=()=>/*c*/X;"
        + statement
        + "return /*r*/X;}function good(){return /*g*/X;}"
    )
    result = capture(source)
    assert any(g.kind == "annex-b" for g in result.gaps)
    for marker in ("p", "c", "r"):
        assert marked(result, marker)[0].state.value == "unknown"
    assert marked(result, "g")[0].state.value == "resolved"
    # No fabricated Annex B var occurrence may be exported.
    assert all(d.kind.value != "var" for d in result.ir.occurrences)


@pytest.mark.parametrize("mode,prefix", [("script", '"use strict";'), ("module", "")])
@pytest.mark.parametrize("statement", ANNEX_POSITIONS[:3])
def test_strict_block_and_case_functions_remain_ordinary(mode, prefix, statement):
    result = capture(
        prefix + "let X;function f(){" + statement + "return /*r*/X;}", mode
    )
    assert not result.gaps
    assert marked(result, "r")[0].state.value == "resolved"


@pytest.mark.parametrize("mode", ["script", "module"])
def test_ordinary_function_declarations_and_switch_discriminant(mode):
    source = (
        "let X;function f(){function Y(){}switch(/*d*/X){case 0:let X;return /*c*/X;}}"
    )
    result = capture(source, mode)
    assert not result.gaps
    assert marked(result, "d")[1] == [(4, 5, "let")]
    start = source.index("let X;return") + 4
    assert marked(result, "c")[1] == [(start, start + 1, "let")]


def test_annex_unit_gap_includes_closures():
    result = capture(
        "let X;switch(0){case 0:function X(){}}function f(){return /*r*/X;}"
    )
    assert marked(result, "r")[0].state.value == "unknown"


@pytest.mark.parametrize(
    "parameters,statement",
    [
        ("eval", 'eval("var X=1");'),
        ("", 'const eval=globalThis.eval;eval("var X=1");'),
        ("", 'let eval=globalThis.eval;eval("var X=1");'),
        ("value", 'let eval=()=>0;eval=value;eval("var X=1");'),
        ("", 'function eval(){}eval("var X=1");'),
        ("", 'const eval=()=>0;eval("var X=1");'),
    ],
)
def test_bound_eval_is_not_a_nonintrinsic_value_proof(parameters, statement):
    source = (
        "let X;function bad("
        + parameters
        + "){const c=()=>/*c*/X;"
        + statement
        + "return /*r*/X;}function good(){return /*g*/X;}"
    )
    result = capture(source)
    assert any(g.kind == "sloppy-direct-eval" for g in result.gaps)
    for marker in ("r", "c"):
        assert marked(result, marker)[0].state.value == "unknown"
    assert marked(result, "g")[1] == [(4, 5, "let")]


@pytest.mark.parametrize(
    "call",
    [
        '(0,eval)("var X=1")',
        'eval?.("var X=1")',
        'globalThis.eval("var X=1")',
        'eval.call(null,"var X=1")',
    ],
)
def test_indirect_eval_does_not_add_local_binding_gap(call):
    result = capture("let X;function f(){" + call + ";return /*r*/X;}")
    assert not result.gaps
    assert marked(result, "r")[1] == [(4, 5, "let")]


@pytest.mark.parametrize("mode,prefix", [("script", '"use strict";'), ("module", "")])
def test_strict_direct_eval_stays_resolved(mode, prefix):
    source = prefix + 'let X;function f(){eval("var X=1");return /*r*/X;}'
    result = capture(source, mode)
    start = source.index("let X") + 4
    assert not result.gaps
    assert marked(result, "r")[1] == [(start, start + 1, "let")]


@pytest.mark.parametrize("mode", ["script", "module"])
@pytest.mark.parametrize("parameters", ["", "p=()=>/*p*/X"])
def test_body_class_uses_lexical_environment_and_actual_shared_token(mode, parameters):
    source = (
        "let X;function f("
        + parameters
        + "){class X {m(){return /*i*/X;}}return /*o*/X;}"
    )
    result = capture(source, mode)
    inside, inner_occurrences = marked(result, "i")
    outside, outer_occurrences = marked(result, "o")
    start = source.index("class X") + 6
    assert inside.target != outside.target
    assert inner_occurrences == outer_occurrences == [(start, start + 1, "class")]
    bindings = {b.id: b for b in result.ir.bindings}
    envs = {e.id: e for e in result.ir.environments}
    assert envs[bindings[outside.target].environment].kind.value == "block"
    assert envs[bindings[inside.target].environment].kind.value == "block"
    assert bindings[inside.target].environment != bindings[outside.target].environment
    assert not result.gaps
    if parameters:
        assert marked(result, "p")[1] == [(4, 5, "let")]


def test_parenthesized_direct_eval_and_default_closure_are_local():
    result = capture(
        'let X;function f(eval,p=()=>/*p*/X){(eval)("var X=1");return /*r*/X;}function g(){return /*g*/X;}'
    )
    for marker in ("p", "r"):
        assert marked(result, marker)[0].state.value == "unknown"
    assert marked(result, "g")[1] == [(4, 5, "let")]
