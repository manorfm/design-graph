"""Native catch bindings and AST-derived static origins, never exception values."""

import os
from dataclasses import replace
from pathlib import Path

import pytest

from .test_binding_capture import provider
from .test_binding_capture_loops import assert_markers


def capture(source, mode="module"):
    return provider().capture(
        source.encode(), locator="catch.js", source_type=mode, syntax="js"
    )


@pytest.mark.parametrize(
    "source,expected",
    [
        (
            (
                "let /*D:outer*/x;try{throw 1;}catch(/*D:caught*/x){"
                "()=>/*closure*/x;}/*after*/x;"
            ),
            {"closure": ["caught"], "after": ["outer"]},
        ),
        (
            "let /*D:outer*/x;try{}catch{let /*D:body*/x;()=>/*body*/x;}/*after*/x;",
            {"body": ["body"], "after": ["outer"]},
        ),
        (
            (
                "/*😀*/const /*D:key*/key='x';let /*D:outer*/x;"
                "try{}catch({[/*key*/key]:/*D:caught*/x=()=>/*default*/x}){"
                "let /*D:body*/key;()=>/*body*/key;()=>/*closure*/x;}/*after*/x;"
            ),
            {
                "key": ["key"],
                "default": ["caught"],
                "body": ["body"],
                "closure": ["caught"],
                "after": ["outer"],
            },
        ),
    ],
)
def test_catch_binding_and_body_sites(source, expected):
    result = capture(source)
    assert_markers(result, expected)
    assert result.ir.units[0].source.encode() == source.encode()
    for occurrence in result.ir.occurrences:
        if (
            "/*D:caught*/" in source
            and occurrence.start == source.encode().index(b"/*D:caught*/") + 12
        ):
            assert occurrence.kind.value == "parameter"
            env = next(
                e for e in result.ir.environments if e.id == occurrence.environment
            )
            assert env.kind.value == "block"
    if os.environ.get("DG_PERSISTENCE_EVIDENCE"):
        out = Path(os.environ["DG_PERSISTENCE_EVIDENCE"], "raw")
        out.mkdir(exist_ok=True)
        (out / (result.ir.units[0].source_sha256 + ".json")).write_text(
            result.to_json()
        )


@pytest.mark.parametrize(
    "mode,prefix", [("script", ""), ("script", "'use strict';"), ("module", "")]
)
def test_simple_catch_var_homonym_kept_distinct_native_cells(mode, prefix):
    source = (
        prefix + "function f(){var /*D:outer*/x;try{}catch(/*D:caught*/x){"
        "var /*D:var*/x=1;()=>/*caught*/x;}return /*after*/x;}"
    )
    result = capture(source, mode)
    assert_markers(result, {"caught": ["caught"], "after": ["outer", "var"]})
    refs = {r.start: r for r in result.ir.references}
    start = source.encode().index(b"/*D:var*/") + len(b"/*D:var*/")
    write = refs[start]
    resolution = next(r for r in result.check().resolutions if r.id == write.id)
    caught = next(d for d in result.ir.occurrences if d.kind.value == "parameter")
    target = next(b for b in result.ir.bindings if b.id == resolution.target)
    assert target.occurrences == (caught.id,)


def test_nested_sibling_catches_loops_switch_and_function_parameter_preservation():
    source = (
        "let /*D:outer*/x;function f({p},...rest){function /*D:fun*/x(){}var /*D:var*/x;"
        "try{}catch([/*D:a*/x=()=>/*default*/x,...tail]){"
        "for(let /*D:loop*/x of []){switch(/*disc*/x){case 0:let /*D:case*/x;/*case*/x;}}"
        "try{}catch(/*D:b*/x){()=>/*nested*/x;}()=>/*a*/x;}"
        "try{}catch(/*D:c*/x){()=>/*sibling*/x;}return /*after*/x;}"
    )
    assert_markers(
        capture(source),
        {
            "default": ["a"],
            "disc": ["loop"],
            "case": ["case"],
            "nested": ["b"],
            "a": ["a"],
            "sibling": ["c"],
            "after": ["fun", "var"],
        },
    )


@pytest.mark.parametrize(
    "mode,prefix", [("script", ""), ("script", "'use strict';"), ("module", "")]
)
def test_destructured_catch_var_homonym_was_refused(mode, prefix):
    with pytest.raises(ValueError):
        capture(prefix + "function f(){try{}catch({x}){var x;}}", mode)


@pytest.mark.parametrize(
    "mode,prefix,unknown",
    [("script", "", True), ("script", "'use strict';", False), ("module", "", False)],
)
def test_catch_block_function_annex_gap_was_sloppy_only(mode, prefix, unknown):
    result = capture(
        prefix
        + "function f(){try{}catch(e){function legacy(){} legacy;}return legacy;}function sibling(){return 1;}",
        mode,
    )
    assert bool(result.gaps) == unknown
    assert all(g.kind == "annex-b" for g in result.gaps)
    resolutions = {r.id: r for r in result.check().resolutions}
    states = [
        resolutions[r.id].state.value
        for r in result.ir.references
        if r.name == "legacy"
    ]
    assert sorted(states) == (
        ["unknown", "unknown"] if unknown else ["resolved", "unresolved"]
    )


def test_nested_function_vars_did_not_trigger_catch_pattern_redeclaration_guard():
    assert_markers(
        capture(
            "try{}catch({/*D:caught*/x}){function f(){var /*D:var*/x;return /*inner*/x;}/*caught*/x;}"
        ),
        {"inner": ["var"], "caught": ["caught"]},
    )


def test_unicode_escaped_catch_tokens_kept_original_byte_offsets():
    source = "/*😀*/let x;try{}catch(\\u0078){()=>\\u0078;}x;"
    result = capture(source)
    token = b"\\u0078"
    raw = source.encode()
    occurrence = next(d for d in result.ir.occurrences if d.kind.value == "parameter")
    assert (occurrence.start, occurrence.end) == (
        raw.index(token),
        raw.index(token) + len(token),
    )
    assert occurrence.name == "x"
    reference = next(r for r in result.ir.references if r.start == raw.rindex(token))
    assert reference.end == reference.start + len(token)
    resolution = next(r for r in result.check().resolutions if r.id == reference.id)
    binding = next(b for b in result.ir.bindings if b.id == resolution.target)
    assert binding.occurrences == (occurrence.id,)


def test_catch_parameter_and_nested_body_shadow_were_separate_cells():
    assert_markers(
        capture(
            "try{}catch(/*D:caught*/x){{let /*D:body*/x;()=>/*body*/x;}/*caught*/x;}"
        ),
        {"body": ["body"], "caught": ["caught"]},
    )


def test_catch_arguments_did_not_replace_function_intrinsic():
    result = capture(
        "function f(){try{}catch(arguments){()=>arguments;}return arguments;}", "script"
    )
    resolutions = {r.id: r for r in result.check().resolutions}
    targets = {
        resolutions[r.id].target for r in result.ir.references if r.name == "arguments"
    }
    assert len(targets) == 2
    assert any(i.binding in targets for i in result.intrinsics)
    assert not result.gaps


def test_catch_parameter_v2_extension_did_not_accept_duplicate_occurrences():
    result = capture("try{}catch(x){x;}")
    d = result.ir.occurrences[0]
    with pytest.raises(ValueError, match="duplicate catch parameter"):
        replace(
            result, ir=replace(result.ir, occurrences=(d, replace(d, id="duplicate")))
        ).check()


def test_catch_origins_rejected_a_real_outer_native_target():
    source = "let /*D:outer*/x;try{}catch(/*D:caught*/x){/*body*/x;}"
    result = capture(source)
    raw = provider()._capture_native(source, "module", "js")
    ref = next(
        r for r in raw["references"] if r["start"] == source.index("/*body*/") + 8
    )
    outer = next(v for v in raw["variables"] if v["name"] == "x")
    ref["target"] = [outer["environment"], "x"]
    ir, intrinsics = provider()._inventory(
        raw, source.encode(), "catch.js", "module", "js"
    )
    forged = provider()._project_references(ir, raw["references"], intrinsics)
    with pytest.raises(ValueError, match="first-binding lookup"):
        replace(result, ir=forged, intrinsics=intrinsics).check()
