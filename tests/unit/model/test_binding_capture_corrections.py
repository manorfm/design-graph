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
