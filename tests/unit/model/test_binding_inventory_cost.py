"""Linear whole-unit inventory lookups without skipping semantic admission."""

import os
from dataclasses import replace
from pathlib import Path

import pytest

from design_graph.capture.binding_capture import BindingCapture
from design_graph.model.binding_ir import EvaluationRegion, EvaluationSlot
from design_graph.model.graph import binding_context as context


@pytest.fixture(scope="module", params=[16, 32])
def capture(request):
    return BindingCapture(
        node=Path(os.environ["DG_CAPTURE_NODE"]),
        toolchain=Path(os.environ["DG_CAPTURE_ENGINE"]),
        fingerprint=os.environ["DG_CAPTURE_FINGERPRINT"],
    ).capture(
        (
            "const x=1;"
            + "".join(f"function f{i}(){{return x;}}" for i in range(request.param))
        ).encode(),
        locator="inventory-cost.js",
        source_type="module",
        syntax="js",
    )


def snapshot(capture):
    return context.BindingSnapshot(
        context.LOGICAL_VERSION,
        "cost",
        (capture,),
        tuple(
            context.BindingRoot(capture.ir.units[0].id, r.id)
            for r in capture.ir.regions
            if r.slot in (EvaluationSlot.ROOT, EvaluationSlot.FUNCTION_CREATION)
        ),
    )


def test_function_inventory_parent_work_is_linear(capture, monkeypatch):
    value = snapshot(capture)
    original = EvaluationRegion.__getattribute__
    counts = {"parent": 0}

    def observe(self, name):
        if name == "parent":
            counts["parent"] += 1
        return original(self, name)

    monkeypatch.setattr(EvaluationRegion, "__getattribute__", observe)
    checked = context._prepare_snapshot(value)
    assert len(checked.results) == 1
    assert counts["parent"] <= 40 * len(capture.ir.regions), counts


def test_inventory_kept_duplicate_missing_and_sibling_slot_refusals(capture):
    value = snapshot(capture)
    parameters = [
        r for r in capture.ir.regions if r.slot == EvaluationSlot.FUNCTION_PARAMETERS
    ]
    for regions in (
        capture.ir.regions + (parameters[0],),
        tuple(r for r in capture.ir.regions if r != parameters[0]),
        tuple(
            replace(r, parent=parameters[1].parent) if r == parameters[0] else r
            for r in capture.ir.regions
        ),
    ):
        altered = replace(capture, ir=replace(capture.ir, regions=regions))
        with pytest.raises(ValueError):
            context._prepare_snapshot(replace(value, captures=(altered,)))


def test_inventory_preserved_full_results_and_canonical_roundtrip(capture):
    value = snapshot(capture)
    checked = context._prepare_snapshot(value)
    decoded = context._decode_snapshot(checked.payload)
    assert (decoded.results, decoded.payload, decoded.revision) == (
        checked.results,
        checked.payload,
        checked.revision,
    )
    assert len(checked.snapshot.roots) == len(capture.functions) + 1
