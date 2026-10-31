"""Static loop sites and native targets, never runtime iteration identities."""

import os
import re
from dataclasses import replace
from pathlib import Path

import pytest

from .test_binding_capture import provider


def capture(source):
    return provider().capture(
        source.encode(), locator="loops.js", source_type="module", syntax="js"
    )


def assert_markers(result, expected):
    source = result.ir.units[0].source.encode()
    refs = {r.start: r for r in result.ir.references}
    resolutions = {r.id: r for r in result.check().resolutions}
    bindings = {b.id: b for b in result.ir.bindings}
    occurrences = {d.id: d for d in result.ir.occurrences}
    for marker, labels in expected.items():
        ref = refs[source.index(("/*" + marker + "*/").encode()) + len(marker) + 4]
        resolution = resolutions[ref.id]
        assert resolution.state.value == "resolved"
        actual = sorted(
            (occurrences[d].start, occurrences[d].end)
            for d in bindings[resolution.target].occurrences
        )
        wanted = []
        for label in labels:
            m = re.search(rb"/\*D:" + label.encode() + rb"\*/([^\W\d]\w*)", source)
            assert m
            wanted.append(m.span(1))
        assert actual == sorted(wanted), marker
    assert result.check().evidence.value == "ir-only"
    assert not result.gaps


@pytest.mark.parametrize(
    "loop,expected",
    [
        (
            "for(let /*D:inner*/x=/*init*/x;/*test*/x;/*update*/x++){()=>/*body*/x;}",
            {k: ["inner"] for k in ("init", "test", "update", "body")},
        ),
        (
            "for(let /*D:inner*/x in /*rhs*/x){()=>/*body*/x;}",
            {k: ["inner"] for k in ("rhs", "body")},
        ),
        (
            "for(const /*D:inner*/x of /*rhs*/x){()=>/*body*/x;}",
            {k: ["inner"] for k in ("rhs", "body")},
        ),
        (
            "for(var /*D:var*/x=/*init*/x;/*test*/x;/*update*/x++){()=>/*body*/x;}",
            {k: ["outer", "var"] for k in ("init", "test", "update", "body")},
        ),
        (
            "for(var /*D:var*/x in /*rhs*/x){()=>/*body*/x;}",
            {k: ["outer", "var"] for k in ("rhs", "body")},
        ),
        (
            "for(var /*D:var*/x of /*rhs*/x){()=>/*body*/x;}",
            {k: ["outer", "var"] for k in ("rhs", "body")},
        ),
    ],
)
def test_loop_lexical_shadowing_and_var_hoisting(loop, expected):
    source = "function f(){var /*D:outer*/x;" + loop + "return /*after*/x;}"
    expected = {
        **expected,
        "after": ["outer", "var"] if "/*D:var*/" in loop else ["outer"],
    }
    assert_markers(capture(source), expected)


def test_nested_sibling_loops_switch_header_and_default_closure():
    source = (
        "const /*D:outer*/x=1;function f(p=()=>/*default*/x){"
        "function /*D:fun*/x(){}var /*D:var*/x;"
        "outer:for(let /*D:a*/x=0;/*test*/x;/*up*/x++){"
        "for(const /*D:b*/x of [/*rhs*/x]){switch(/*disc*/x){"
        "case 0:let /*D:case*/x;()=>/*case*/x;break;}()=>/*nested*/x;continue outer;}"
        "()=>/*a*/x;break outer;}"
        "for(let /*D:c*/x of []){()=>/*sibling*/x;}return /*end*/x;}"
    )
    assert_markers(
        capture(source),
        {
            "default": ["outer"],
            "test": ["a"],
            "up": ["a"],
            "rhs": ["b"],
            "disc": ["b"],
            "case": ["case"],
            "nested": ["b"],
            "a": ["a"],
            "sibling": ["c"],
            "end": ["fun", "var"],
        },
    )


@pytest.mark.parametrize("operator", ["in", "of"])
def test_destructuring_computed_defaults_and_unicode_offsets(operator):
    source = (
        "/*😀*/const /*D:key*/key='a';let /*D:outer*/x;"
        "for(let {[/*key*/key]:/*D:inner*/x=()=>/*default*/x} "
        + operator
        + " /*rhs*/x){()=>/*body*/x;}/*after*/x;"
    )
    assert_markers(
        capture(source),
        {
            "key": ["key"],
            "default": ["inner"],
            "rhs": ["inner"],
            "body": ["inner"],
            "after": ["outer"],
        },
    )


@pytest.mark.parametrize(
    "loop",
    [
        "for(;/*test*/x;){/*body*/x;break;}",
        "for(/*test*/x in []){/*body*/x;}",
        "for(/*test*/x of []){/*body*/x;}",
    ],
)
def test_assignment_and_empty_headers_did_not_create_lexical_cells(loop):
    assert_markers(capture("let /*D:x*/x;" + loop), {"test": ["x"], "body": ["x"]})


def test_raw_loop_source_was_preserved_and_never_executed():
    source = (
        "throw new Error('SOURCE_MUST_NOT_EXECUTE');process.exit(91);"
        "/*😀*/let /*D:outer*/x;for(let /*D:inner*/x=0;/*test*/x;){()=>/*body*/x;}"
    )
    result = capture(source)
    assert result.ir.units[0].source.encode() == source.encode()
    assert_markers(result, {"test": ["inner"], "body": ["inner"]})
    if os.environ.get("DG_PERSISTENCE_EVIDENCE"):
        Path(os.environ["DG_PERSISTENCE_EVIDENCE"], "loop-raw-capture.json").write_text(
            result.to_json()
        )


def test_loop_origins_are_site_derived_not_native_target_derived():
    source = (
        "let /*D:outer*/x;for(let /*D:inner*/x=0;/*test*/x;){/*body*/x;}/*after*/x;"
    )
    result = capture(source)
    assert_markers(result, {"test": ["inner"], "body": ["inner"], "after": ["outer"]})
    raw = provider()._capture_native(source, "module", "js")
    reference = next(
        r for r in raw["references"] if r["start"] == source.index("/*test*/") + 8
    )
    outer = next(v for v in raw["variables"] if v["name"] == "x")
    reference["target"] = [outer["environment"], "x"]
    ir, intrinsics = provider()._inventory(
        raw, source.encode(), "loops.js", "module", "js"
    )
    forged = provider()._project_references(ir, raw["references"], intrinsics)
    with pytest.raises(ValueError, match="first-binding lookup"):
        replace(result, ir=forged, intrinsics=intrinsics).check()
