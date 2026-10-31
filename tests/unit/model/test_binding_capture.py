"""Real producer-to-checker controls; engine location is explicitly supplied."""

import importlib
import importlib.util
import json
import os
import re
from functools import lru_cache
from hashlib import sha256
from pathlib import Path

import pytest


@lru_cache(maxsize=1)
def provider():
    module = (
        importlib.import_module("design_graph.capture.binding_capture")
        if importlib.util.find_spec("design_graph.capture.binding_capture")
        else None
    )
    assert module is not None, "whole-unit binding capture capability is missing"
    return module.BindingCapture(
        node=Path(os.environ["DG_CAPTURE_NODE"]),
        toolchain=Path(os.environ["DG_CAPTURE_ENGINE"]),
        fingerprint=os.environ["DG_CAPTURE_FINGERPRINT"],
    )


def test_whole_unit_function_var_default_closure():
    source = "const X=1;function f(p=()=>/*d*/X){function X(){}var X;return /*b*/X;}"
    capture = provider().capture(
        source.encode(), locator="unit.js", source_type="module", syntax="js"
    )
    assert capture.ir.units[0].source == source
    assert capture.check().evidence.value == "ir-only"
    ds = {d.id: d for d in capture.ir.occurrences}
    refs = {r.id: r for r in capture.ir.references}
    found = {}
    for resolution in capture.check().resolutions:
        ref = refs[resolution.id]
        if ref.name == "X" and ref.access.value == "read":
            binding = next(b for b in capture.ir.bindings if b.id == resolution.target)
            found[source.encode()[: ref.start].decode()[-5:]] = sorted(
                ds[d].kind.value for d in binding.occurrences
            )
    assert found == {"/*d*/": ["const"], "/*b*/": ["function", "var"]}


FIXTURES = Path(__file__).with_name("binding_capture_fixtures")


def load(name):
    return json.loads((FIXTURES / name).read_text())


def captured_fixture(f):
    result = provider().capture(
        f["source"].encode(),
        locator=f["name"] + ".js",
        source_type=f.get("mode", "module"),
        syntax=f.get("syntax", "js"),
    )
    if os.environ.get("DG_CAPTURE_EVIDENCE"):
        Path(os.environ["DG_CAPTURE_EVIDENCE"], f["name"] + ".json").write_text(
            result.to_json()
        )
    return result


def marked(capture, marker):
    source = capture.ir.units[0].source.encode()
    offset = source.index(("/*" + marker + "*/").encode()) + len(marker) + 4
    refs = [r for r in capture.ir.references if r.start == offset]
    assert len(refs) == 1, (marker, refs)
    result = next(r for r in capture.check().resolutions if r.id == refs[0].id)
    assert result.target is not None, (marker, result)
    return next(b for b in capture.ir.bindings if b.id == result.target)


@pytest.mark.parametrize(
    "f",
    load("class-controls.json") + load("arguments-controls.json"),
    ids=lambda f: f["name"],
)
def test_expanded_real_controls(f):
    capture = captured_fixture(f)
    declarations = {d.id: d for d in capture.ir.occurrences}
    source = f["source"].encode()
    for marker, labels in f["defs"].items():
        target = marked(capture, marker)
        expected = []
        for label in labels:
            m = re.search(rb"/\*D:" + label.encode() + rb"\*/\s*([^\W\d]\w*)", source)
            assert m is not None
            expected.append([m.start(1), m.end(1)])
        actual = sorted(
            [[declarations[d].start, declarations[d].end] for d in target.occurrences]
        )
        assert actual == sorted(expected)
    for left, right, same in f.get("relations", []):
        assert (marked(capture, left).id == marked(capture, right).id) == same
    for marker in f.get("implicit", []):
        target = marked(capture, marker)
        assert target.occurrences == ()
        assert any(
            i.binding == target.id and i.kind == "arguments" for i in capture.intrinsics
        )


@pytest.mark.parametrize("f", load("fixtures.json"), ids=lambda f: f["name"])
def test_reused_44_whole_units(f):
    assert sha256(f["source"].encode()).hexdigest() == f["sha256"]
    if f["syntax"] in ("ts", "tsx"):
        with pytest.raises(ValueError, match="explicit supported"):
            captured_fixture(f)
        return
    capture = captured_fixture(f)
    assert capture.ir.units[0].source.encode() == f["source"].encode()
    declarations = {d.id: d for d in capture.ir.occurrences}
    for marker, expected in load("expectations.json")["fixtures"][f["name"]].items():
        target = marked(capture, marker)
        actual = sorted(
            [[declarations[d].start, declarations[d].end] for d in target.occurrences]
        )
        assert actual == expected
    if f["name"] in ("homonym_init", "homonym_uninit", "homonym_copy"):
        assert marked(capture, "d").id != marked(capture, "b").id
    if f["origin"] == "additional spike boundary":
        assert (marked(capture, "d").id == marked(capture, "b").id) == (
            f["name"] == "arguments_single"
        )
    if f["name"] in ("with", "eval", "annexb"):
        assert any(r.state.value == "unknown" for r in capture.check().resolutions)
    from design_graph.model.binding_capture_ir import BindingCaptureIR

    assert BindingCaptureIR.from_json(capture.to_json()).to_json() == capture.to_json()


@pytest.mark.parametrize(
    "source",
    [
        "const x:number=1;",
        "interface X {}",
        "declare const x: number;",
    ],
)
def test_js_options_do_not_silently_admit_typescript(source):
    with pytest.raises(ValueError, match="engine capture refused"):
        provider().capture(
            source.encode(), locator="unit.js", source_type="module", syntax="js"
        )


def test_pin_is_rechecked_on_every_capture(tmp_path):
    import shutil

    from design_graph.capture.binding_capture import BindingCapture

    engine = Path(os.environ["DG_CAPTURE_ENGINE"])
    # A changed API fails even on an already configured provider; no discovery.
    copied = tmp_path / "toolchain"
    copied.mkdir()
    for name in (
        "corrected-scope-manager",
        "node_modules",
        "engine-final.patch",
        "package-lock.json",
    ):
        (copied / name).symlink_to(
            engine / name, target_is_directory=(engine / name).is_dir()
        )
    shutil.copyfile(engine / "engine-api.mjs", copied / "engine-api.mjs")
    capture = BindingCapture(
        node=Path(os.environ["DG_CAPTURE_NODE"]),
        toolchain=copied,
        fingerprint=os.environ["DG_CAPTURE_FINGERPRINT"],
    )
    (copied / "engine-api.mjs").write_text(
        (copied / "engine-api.mjs").read_text() + "\n// changed\n"
    )
    with pytest.raises(ValueError, match="toolchain artifact mismatch"):
        capture.capture(
            b"const x=1;", locator="unit.js", source_type="module", syntax="js"
        )


def test_forged_arguments_on_arrow_is_rejected():
    from dataclasses import replace

    from design_graph.model.binding_capture_ir import IntrinsicBinding, binding_id
    from design_graph.model.binding_ir import Binding, Namespace

    capture = provider().capture(
        b"const f=()=>missing;", locator="arrow.js", source_type="module", syntax="js"
    )
    environment = next(
        e for e in capture.ir.environments if e.kind.value == "function-shared"
    )
    id_ = binding_id(environment.unit, environment.id, "arguments")
    fake = Binding(
        id_, environment.unit, environment.id, Namespace.VALUE, "arguments", ()
    )
    capture = replace(
        capture,
        ir=replace(capture.ir, bindings=(*capture.ir.bindings, fake)),
        intrinsics=(
            *capture.intrinsics,
            IntrinsicBinding(id_, environment.id, environment.unit, "arguments"),
        ),
    )
    with pytest.raises(ValueError, match="ordinary"):
        capture.check()


def test_unicode_escapes_emoji_crlf_and_switch_phases():
    source = "const \\u0058=1;/* 😀 */\r\nfunction f(p=()=>/*d*/X){switch(/*s*/X){case /*t*/X:const X=2;return /*b*/X;}}"
    capture = provider().capture(
        source.encode(), locator="unicode.js", source_type="module", syntax="js"
    )
    outer = marked(capture, "d")
    assert outer.id == marked(capture, "s").id
    assert outer.id != marked(capture, "t").id == marked(capture, "b").id
    declarations = {d.id: d for d in capture.ir.occurrences}
    assert (
        source.encode()[
            declarations[outer.occurrences[0]].start : declarations[
                outer.occurrences[0]
            ].end
        ]
        == b"\\u0058"
    )
    assert (
        capture.check().initialization.value == capture.check().value.value == "unknown"
    )
    assert capture.ir.units[0].source.encode() == source.encode()


def test_real_switch_scope_and_target_relabel_is_rejected():
    from dataclasses import replace

    capture = provider().capture(
        b"const X=1;function f(){switch(/*s*/X){case 0:const X=2;return /*b*/X;}}",
        locator="switch.js",
        source_type="module",
        syntax="js",
    )
    case_binding = marked(capture, "b")
    outer_binding = marked(capture, "s")
    source = capture.ir.units[0].source.encode()
    ref = next(
        r for r in capture.ir.references if r.start == source.index(b"/*s*/") + 5
    )
    old = next(r for r in capture.ir.resolutions if r.id == ref.id)
    bad = replace(
        old,
        origin=case_binding.environment,
        target=case_binding.id,
        path=(case_binding.environment,),
    )
    with pytest.raises(ValueError, match="derived first-binding"):
        replace(
            capture,
            ir=replace(
                capture.ir,
                resolutions=tuple(
                    bad if r.id == bad.id else r for r in capture.ir.resolutions
                ),
            ),
        ).check()
    assert outer_binding.id != case_binding.id


@pytest.mark.parametrize(
    "source,marker,kind",
    [
        (
            'let X;function bad(){eval("var X=1");return /*b*/X;}function good(){return /*g*/X;}',
            "b",
            "sloppy-direct-eval",
        ),
        (
            "let X;function bad(o){with(o){return /*b*/X;}}function good(){return /*g*/X;}",
            "b",
            "dynamic-with",
        ),
        (
            "let X;function bad(){if(1){function X(){}}return /*b*/X;}function good(){return /*g*/X;}",
            "b",
            "annex-b",
        ),
    ],
)
def test_dynamic_gaps_are_local_not_sibling_poison(source, marker, kind):
    capture = provider().capture(
        source.encode(), locator="dynamic.js", source_type="script", syntax="js"
    )
    assert any(g.kind == kind for g in capture.gaps)

    def state(mark):
        pos = source.encode().index(("/*" + mark + "*/").encode()) + len(mark) + 4
        ref = next(r for r in capture.ir.references if r.start == pos)
        return next(
            r.state.value for r in capture.check().resolutions if r.id == ref.id
        )

    assert state(marker) == "unknown"
    assert state("g") == "resolved"


def test_offline_patch_recipe_reproduces_real_engine(tmp_path):
    import subprocess
    import sys

    script = (
        Path(__file__).parents[3] / "src/design_graph/capture/binding_engine/prepare.py"
    )
    assert script.is_file(), "maintained offline corrected-engine recipe is missing"
    destination = tmp_path / "prepared"
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(script),
            "--dependencies",
            str(Path(os.environ["DG_CAPTURE_ENGINE"]) / "node_modules"),
            "--output",
            str(destination),
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    from design_graph.capture.binding_capture import BindingCapture

    captured = BindingCapture(
        node=Path(os.environ["DG_CAPTURE_NODE"]),
        toolchain=destination,
        fingerprint=os.environ["DG_CAPTURE_FINGERPRINT"],
    ).capture(
        b"function f(){var x;var x;return x;}",
        locator="recipe.js",
        source_type="module",
        syntax="js",
    )
    assert any(len(b.occurrences) == 2 for b in captured.ir.bindings)


@pytest.mark.parametrize("source_type", ["module", "script"])
@pytest.mark.parametrize(
    "declaration", ["var X;var X;", "function X(){}var X;", "var X;function X(){}"]
)
def test_static_root_declarations_are_real_canonical_bindings(source_type, declaration):
    source = declaration + "function f(){return /*r*/X;}"
    capture = provider().capture(
        source.encode(), locator="root.js", source_type=source_type, syntax="js"
    )
    assert len(marked(capture, "r").occurrences) == 2
    assert not capture.gaps


@pytest.mark.parametrize(
    "source",
    [
        b"\xef\xbb\xbf/* header */\r\nconst X=1;X;",
        "/* 😀 */\r\nconst X=1;X;\r\n".encode(),
    ],
)
def test_exact_whole_unit_includes_bom_comments_and_trailing_bytes(source):
    capture = provider().capture(
        source, locator="bytes.js", source_type="module", syntax="js"
    )
    assert capture.ir.units[0].source.encode() == source
    root = next(r for r in capture.ir.regions if r.slot.value == "root")
    assert (root.start, root.end) == (0, len(source))


def test_required_toolchain_configuration_fails_closed(tmp_path):
    from design_graph.capture.binding_capture import BindingCapture

    with pytest.raises(TypeError):
        BindingCapture()
    with pytest.raises(ValueError, match="fingerprint"):
        BindingCapture(
            node=Path(os.environ["DG_CAPTURE_NODE"]),
            toolchain=Path(os.environ["DG_CAPTURE_ENGINE"]),
            fingerprint="0" * 64,
        )
    with pytest.raises(ValueError, match="explicit absolute"):
        BindingCapture(
            node=Path(os.environ["DG_CAPTURE_NODE"]),
            toolchain=tmp_path / "absent",
            fingerprint=os.environ["DG_CAPTURE_FINGERPRINT"],
        )
