"""Finite reader calibration; generated sources are explicitly synthetic."""

import os
from dataclasses import replace
from pathlib import Path

import pytest

from design_graph.capture.binding_capture import BindingCapture
from design_graph.model.graph import binding_context as context


@pytest.fixture(scope="module")
def capture():
    return BindingCapture(
        node=Path(os.environ["DG_CAPTURE_NODE"]),
        toolchain=Path(os.environ["DG_CAPTURE_ENGINE"]),
        fingerprint=os.environ["DG_CAPTURE_FINGERPRINT"],
    ).capture(
        (
            "const x=1;" + "".join(f"function f{i}(){{return x;}}" for i in range(256))
        ).encode(),
        locator="synthetic-finite.js",
        source_type="module",
        syntax="js",
    )


def roots(capture):
    return tuple(
        context.BindingRoot(capture.ir.units[0].id, region.id)
        for region in capture.ir.regions
        if region.slot.value in ("root", "function-creation")
    )


def test_complete_synthetic_inventory_above_historical_root_cap(capture):
    inventory = roots(capture)
    assert len(inventory) == len(set(inventory)) == 257
    snapshot = context.BindingSnapshot.create("finite", (capture,), inventory)
    assert context.BindingSnapshot.from_json(snapshot.to_json()).roots == tuple(
        sorted(inventory)
    )


def test_finite_profile_is_closed_and_versioned():
    assert (
        context.MAX_JSON_CHARS,
        context.MAX_JSON_BYTES,
        context.MAX_RECORDS,
        context.MAX_DEPTH,
        context.MAX_UNITS,
        context.MAX_ROOTS,
    ) == (16 * 1024 * 1024, 64 * 1024 * 1024, 100_000, 64, 64, 4096)
    assert context.LOGICAL_VERSION == "binding-context/2"


@pytest.mark.parametrize("kind", ["characters", "objects", "depth"])
def test_predecode_exact_boundary_and_over(kind, monkeypatch):
    if kind == "characters":
        text = '"' + "x" * (context.MAX_JSON_CHARS - 2) + '"'
        over = text + " "
    elif kind == "objects":
        text = "[" + ",".join("{}" for _ in range(context.MAX_RECORDS)) + "]"
        over = "[{}," + text[1:]
    else:
        text = "[" * context.MAX_DEPTH + "0" + "]" * context.MAX_DEPTH
        over = "[" + text + "]"
    context._admit(text)
    monkeypatch.setattr(
        context.json, "loads", lambda *a, **k: pytest.fail("decoded oversized input")
    )
    with pytest.raises(ValueError, match="budget exceeded"):
        context.BindingSnapshot.from_json(over)


def test_utf8_budget_is_independent(monkeypatch):
    # Lowered local ceilings exercise the otherwise dominated four-byte bound.
    monkeypatch.setattr(context, "MAX_JSON_BYTES", 10)
    context._admit('"éééé"')
    with pytest.raises(ValueError, match="byte budget exceeded"):
        context._admit('"ééééé"')


@pytest.mark.parametrize(
    "kind", ["empty", "duplicate", "unknown", "cross-unit", "over"]
)
def test_invalid_roots_remain_closed(capture, kind):
    inventory = roots(capture)
    invalid = {
        "empty": (),
        "duplicate": (inventory[0], inventory[0]),
        "unknown": (replace(inventory[0], region="absent"),),
        "cross-unit": (replace(inventory[0], unit="absent"),),
        "over": inventory * (context.MAX_ROOTS // len(inventory) + 1),
    }[kind]
    with pytest.raises(ValueError):
        context.BindingSnapshot.create("finite", (capture,), invalid)


def test_unit_budget_refuses_before_checking(capture, monkeypatch):
    monkeypatch.setattr(
        type(capture),
        "_check_decoded",
        lambda *a: pytest.fail("checked overbudget units"),
    )
    with pytest.raises(ValueError, match="unit budget"):
        context.BindingSnapshot.create("finite", (capture,) * 65, roots(capture))


def test_manifest_kept_its_own_object_ceiling(tmp_path):
    from design_graph.pipeline.binding_completion import read_manifest

    path = tmp_path / "oversized-manifest.json"
    path.write_text("[" + ",".join("{}" for _ in range(20_001)) + "]")
    with pytest.raises(ValueError, match="budget exceeded"):
        read_manifest(path, {"coverage": []}, "0" * 64)


def test_stored_oversize_refused_before_decode(tmp_path, monkeypatch):
    import kuzu

    database = kuzu.Database(
        str(tmp_path / "corrupt.db"),
        buffer_pool_size=128 * 1024 * 1024,
        max_num_threads=2,
    )
    connection = kuzu.Connection(database)
    revision = "0" * 64
    try:
        context._rows(
            connection,
            "CREATE NODE TABLE BindingContextSnapshot(snapshot_id STRING PRIMARY KEY, format STRING, payload STRING)",
        )
        # Fresh corrupt-input DB avoids unproven large UPDATE pool headroom.
        text = " " * (context.MAX_JSON_CHARS + 1)
        context._rows(
            connection,
            "CREATE (:BindingContextSnapshot {snapshot_id:$id,format:$format,payload:$payload})",
            {"id": revision, "format": context.PHYSICAL_VERSION, "payload": text},
        )
        assert context._rows(
            connection, "MATCH (s:BindingContextSnapshot) RETURN size(s.payload)"
        ) == [[len(text)]]
        monkeypatch.setattr(
            context,
            "_decode_snapshot",
            lambda *a: pytest.fail("fetched oversized stored payload"),
        )
        with pytest.raises(ValueError, match="pre-fetch character budget"):
            context.read_binding_context(connection, revision)
    finally:
        connection.close()
        database.close()


@pytest.mark.parametrize("kind", ["objects", "depth"])
def test_stored_shape_refused_before_json_decode(tmp_path, monkeypatch, kind):
    import kuzu

    database = kuzu.Database(
        str(tmp_path / "corrupt.db"),
        buffer_pool_size=128 * 1024 * 1024,
        max_num_threads=2,
    )
    connection = kuzu.Connection(database)
    revision = "0" * 64
    text = (
        ("[" + ",".join("{}" for _ in range(context.MAX_RECORDS + 1)) + "]")
        if kind == "objects"
        else ("[" * 65 + "0" + "]" * 65)
    )
    try:
        context._rows(
            connection,
            "CREATE NODE TABLE BindingContextSnapshot(snapshot_id STRING PRIMARY KEY, format STRING, payload STRING)",
        )
        context._rows(
            connection,
            "CREATE (:BindingContextSnapshot {snapshot_id:$id,format:$format,payload:$payload})",
            {"id": revision, "format": context.PHYSICAL_VERSION, "payload": text},
        )
        assert context._rows(
            connection, "MATCH (s:BindingContextSnapshot) RETURN s.payload"
        ) == [[text]]
        monkeypatch.setattr(
            context.json,
            "loads",
            lambda *a, **k: pytest.fail("decoded oversized stored shape"),
        )
        with pytest.raises(ValueError, match="depth/record budget"):
            context.read_binding_context(connection, revision)
    finally:
        connection.close()
        database.close()


def test_historical_logical_version_refuses(capture):
    value = context.BindingSnapshot(
        "binding-context/1", "finite", (capture,), roots(capture)[:1]
    )
    with pytest.raises(ValueError, match="version"):
        value.validate()
