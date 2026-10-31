"""Invocation-local checking: cost gates and strict direct-object admission."""

import json
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import kuzu
import pytest

from design_graph.capture.binding_capture import BindingCapture
from design_graph.model import binding_capture_ir as capture_ir
from design_graph.model.binding_public_context import project_binding_context
from design_graph.model.graph import binding_context as context


@pytest.fixture(scope="module")
def capture():
    return BindingCapture(
        node=Path(os.environ["DG_CAPTURE_NODE"]),
        toolchain=Path(os.environ["DG_CAPTURE_ENGINE"]),
        fingerprint=os.environ["DG_CAPTURE_FINGERPRINT"],
    ).capture(
        b"const x=1;function f(p=()=>x){var x;return p;}try{}catch(e){e;}",
        locator="cost.js",
        source_type="module",
        syntax="js",
    )


def snapshot(capture):
    unit = capture.ir.units[0]
    return context.BindingSnapshot.create(
        "cost", (capture,), (context.BindingRoot(unit.id, unit.root_region),)
    )


def counted(monkeypatch):
    counts = {
        "semantic": 0,
        "snapshot_decode": 0,
        "capture_decode": 0,
        "canonical": 0,
        "capture_asdict": 0,
    }
    canonical = context.BindingSnapshot._canonical_json
    asdict = capture_ir.asdict

    def serialize(self):
        counts["canonical"] += 1
        return canonical(self)

    def copy_capture(value):
        counts["capture_asdict"] += 1
        return asdict(value)

    monkeypatch.setattr(context.BindingSnapshot, "_canonical_json", serialize)
    monkeypatch.setattr(capture_ir, "asdict", copy_capture)
    original = capture_ir._CaptureChecker.run

    def run(self):
        counts["semantic"] += 1
        return original(self)

    monkeypatch.setattr(capture_ir._CaptureChecker, "run", run)
    for module in (context, capture_ir):
        decode = module._decode

        def wrapper(type_, value, decode=decode):
            if type_ is context.BindingSnapshot:
                counts["snapshot_decode"] += 1
            if type_ is capture_ir.BindingCaptureIR:
                counts["capture_decode"] += 1
            return decode(type_, value)

        monkeypatch.setattr(module, "_decode", wrapper)
    return counts


def test_direct_projection_checked_once(capture, monkeypatch):
    value = snapshot(capture)
    counts = counted(monkeypatch)
    project_binding_context(
        value, unit=value.roots[0].unit, region=value.roots[0].region
    )
    assert counts == {
        "semantic": 1,
        "snapshot_decode": 0,
        "capture_decode": 0,
        "canonical": 1,
        "capture_asdict": 1,
    }


def test_direct_writer_checked_once(tmp_path, capture, monkeypatch):
    value = snapshot(capture)
    db = kuzu.Database(
        str(tmp_path / "writer.db"),
        buffer_pool_size=128 * 1024 * 1024,
        max_num_threads=2,
    )
    conn = kuzu.Connection(db)
    counts = counted(monkeypatch)
    try:
        revision = context.write_binding_context(conn, value)
        assert counts == {
            "semantic": 1,
            "snapshot_decode": 0,
            "capture_decode": 0,
            "canonical": 1,
            "capture_asdict": 1,
        }
        result = conn.execute("MATCH (s:BindingContextSnapshot) RETURN s.snapshot_id")
        assert result.get_all() == [[revision]]
        result.close()
    finally:
        conn.close()
        db.close()


def test_transport_decoded_once_checked_once(capture, monkeypatch):
    text = snapshot(capture).to_json()
    counts = counted(monkeypatch)
    assert context.BindingSnapshot.from_json(text).community == "cost"
    assert counts == {
        "semantic": 1,
        "snapshot_decode": 1,
        "capture_decode": 0,
        "canonical": 1,
        "capture_asdict": 1,
    }


def test_normal_query_checks_once_each_invocation(
    tmp_path, capture, monkeypatch, capsys
):
    from design_graph.interface.cli.binding_query import run_binding_query

    value = snapshot(capture)
    path = tmp_path / "cost.db"
    db = kuzu.Database(str(path), buffer_pool_size=128 * 1024 * 1024, max_num_threads=2)
    conn = kuzu.Connection(db)
    revision = context.write_binding_context(conn, value)
    conn.close()
    db.close()
    args = SimpleNamespace(
        db_path=path,
        snapshot=revision,
        expected_sha256=revision,
        unit=value.roots[0].unit,
        region=value.roots[0].region,
    )
    counts = counted(monkeypatch)
    for invocation in (1, 2):
        run_binding_query(args)
        assert json.loads(capsys.readouterr().out)["snapshot"] == revision
        assert counts == {
            "semantic": invocation,
            "snapshot_decode": invocation,
            "capture_decode": 0,
            "canonical": invocation,
            "capture_asdict": invocation,
        }


@pytest.mark.parametrize(
    "field,bad",
    [("complete", 1), ("start", False), ("parent", 123), ("slot", "invalid")],
)
def test_direct_malformed_frozen_descendants_refuse(capture, field, bad):
    region = replace(capture.ir.regions[0], **{field: bad})
    forged = replace(
        capture, ir=replace(capture.ir, regions=(region, *capture.ir.regions[1:]))
    )
    with pytest.raises(ValueError):
        forged.check()
    with pytest.raises(ValueError):
        snapshot(forged)


@pytest.mark.parametrize("which", ["references", "regions", "bindings", "resolutions"])
def test_deep_mutable_descendants_refuse(capture, which):
    forged = replace(
        capture, ir=replace(capture.ir, **{which: list(getattr(capture.ir, which))})
    )
    with pytest.raises(ValueError):
        forged.check()
    with pytest.raises(ValueError):
        snapshot(forged)


def test_normal_build_checked_and_canonicalized_once(tmp_path):
    from tests.unit.pipeline.test_binding_cli import build

    html = tmp_path / "small.html"
    html.write_text(
        "<html><body><main>Cost</main><script>const x=1;function f(){return x;}</script></body></html>"
    )
    db = tmp_path / "built.db"
    receipt = tmp_path / "counts.json"
    instrument = f"""\nimport atexit, json
from pathlib import Path
from design_graph.model.binding_capture_ir import _CaptureChecker
from design_graph.model.graph.binding_context import BindingSnapshot
counts = {{"semantic": 0, "canonical": 0}}
original = _CaptureChecker.run
def run(self):
 counts["semantic"] += 1
 return original(self)
_CaptureChecker.run = run
# Count the snapshot's canonical entry in both old and corrected code.
name = "_canonical_json" if hasattr(BindingSnapshot, "_canonical_json") else "to_json"
canonical = getattr(BindingSnapshot, name)
def serialize(self):
 counts["canonical"] += 1
 return canonical(self)
setattr(BindingSnapshot, name, serialize)
atexit.register(lambda: Path({str(receipt)!r}).write_text(json.dumps(counts)))
"""
    result = build(html, db, before=instrument)
    assert result.returncode == 0, result.stderr
    assert json.loads(receipt.read_text()) == {"semantic": 1, "canonical": 1}
    manifest = json.loads(Path(str(db) + ".binding.json").read_text())
    assert manifest["contract"] == "binding-build/3" and manifest["general"]
    unchanged = build(html, db, before=instrument)
    assert unchanged.returncode == 0, unchanged.stderr
    assert json.loads(unchanged.stdout)["status"] == "skipped"
    assert json.loads(receipt.read_text()) == {"semantic": 1, "canonical": 1}


def test_same_connection_mutated_bytes_are_checked_next_call(
    tmp_path, capture, monkeypatch
):
    from design_graph.model.binding_public_context import read_project_binding_context

    value = snapshot(capture)
    db = kuzu.Database(
        str(tmp_path / "mutable.db"),
        buffer_pool_size=128 * 1024 * 1024,
        max_num_threads=2,
    )
    conn = kuzu.Connection(db)
    try:
        revision = context.write_binding_context(conn, value)
        root = value.roots[0]
        counts = counted(monkeypatch)
        assert (
            read_project_binding_context(
                conn, revision, unit=root.unit, region=root.region
            )["snapshot"]
            == revision
        )
        changed = json.loads(value._canonical_json())
        changed["captures"][0]["ir"]["resolutions"][0]["origin"] = "forged"
        text = json.dumps(changed)
        conn.execute(
            "MATCH (s:BindingContextSnapshot) SET s.payload=$payload", {"payload": text}
        ).close()
        result = conn.execute("MATCH (s:BindingContextSnapshot) RETURN s.payload")
        assert result.get_all() == [[text]]
        result.close()
        with pytest.raises(ValueError):
            read_project_binding_context(
                conn, revision, unit=root.unit, region=root.region
            )
        assert counts["semantic"] == 2 and counts["snapshot_decode"] == 2
    finally:
        conn.close()
        db.close()


def test_public_projection_refuses_claimed_checked_handle(capture):
    # The ordinary API accepts a snapshot, not even an actual internal context.
    value = snapshot(capture)
    checked = context._prepare_snapshot(value)
    for supplied in (
        checked,
        SimpleNamespace(
            snapshot=value,
            results=checked.results,
            payload=checked.payload,
            revision=checked.revision,
        ),
    ):
        with pytest.raises(ValueError):
            project_binding_context(
                supplied, unit=value.roots[0].unit, region=value.roots[0].region
            )
    # Selection cannot hide malformed facts behind an unknown requested root.
    bad = replace(value, roots=list(value.roots))
    with pytest.raises(ValueError):
        project_binding_context(bad, unit="unknown", region="unknown")


def test_exact_typed_tuple_arity_and_nested_scalar_types(capture):
    from dataclasses import dataclass

    from design_graph.model.binding_ir import _validate_typed

    @dataclass(frozen=True)
    class Pair:
        fields: tuple[str, int]

    _validate_typed(Pair, Pair(("x", 1)))
    for bad in (("x",), ("x", 1, 2), ("x", True), ["x", 1]):
        with pytest.raises(ValueError):
            _validate_typed(Pair, Pair(bad))
    resolution = replace(capture.ir.resolutions[0], path=(123,))
    forged = replace(
        capture,
        ir=replace(capture.ir, resolutions=(resolution, *capture.ir.resolutions[1:])),
    )
    with pytest.raises(ValueError):
        forged.check()


def test_unchanged_product_caps():
    assert (
        context.MAX_JSON_CHARS,
        context.MAX_JSON_BYTES,
        context.MAX_RECORDS,
        context.MAX_DEPTH,
        context.MAX_UNITS,
        context.MAX_ROOTS,
    ) == (2097152, 8388608, 20000, 64, 64, 256)
