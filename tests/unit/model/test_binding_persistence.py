"""Real Kuzu cold-read vertical; no legacy private-context dependencies."""

import importlib.util
import json
import os
import subprocess
import time
from pathlib import Path

import kuzu
import pytest

from design_graph.capture.binding_capture import BindingCapture


@pytest.fixture(scope="module")
def captured():
    provider = BindingCapture(
        node=Path(os.environ["DG_CAPTURE_NODE"]),
        toolchain=Path(os.environ["DG_CAPTURE_ENGINE"]),
        fingerprint=os.environ["DG_CAPTURE_FINGERPRINT"],
    )
    start = time.perf_counter()
    value = provider.capture(
        b"const X=1;function Probe(p=()=>/*d*/X){function X(){}var X;return /*b*/X;}function Other(){return 'PRIVATE_OTHER_BODY';}",
        locator="vertical.js",
        source_type="module",
        syntax="js",
    )
    return value, time.perf_counter() - start


def capability():
    name = "design_graph.model.graph.binding_context"
    assert importlib.util.find_spec(name), (
        "real persisted binding context capability missing"
    )
    return __import__(name, fromlist=["BindingSnapshot"])


def database(path, readonly=False):
    return kuzu.Database(
        str(path),
        buffer_pool_size=128 * 1024 * 1024,
        max_num_threads=2,
        read_only=readonly,
    )


def test_capture_commit_close_reopen_readonly_public_without_node(
    tmp_path, captured, monkeypatch
):
    api = capability()
    capture, capture_seconds = captured
    unit = capture.ir.units[0].id
    root = next(
        r
        for r in capture.ir.regions
        if r.slot.value == "function-creation"
        and capture.ir.units[0]
        .source.encode()[r.start : r.end]
        .startswith(b"function Probe")
    )
    snapshot = api.BindingSnapshot.create(
        "community:test", (capture,), (api.BindingRoot(unit, root.id),)
    )
    path = tmp_path / "vertical.kuzu"
    db = database(path)
    conn = kuzu.Connection(db)
    start = time.perf_counter()
    revision = api.write_binding_context(conn, snapshot)
    write_seconds = time.perf_counter() - start
    conn.close()
    db.close()
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *a, **k: pytest.fail("retrieval launched a subprocess"),
    )
    start = time.perf_counter()
    db = database(path, True)
    conn = kuzu.Connection(db)
    reopen_seconds = time.perf_counter() - start
    try:
        start = time.perf_counter()
        loaded = api.read_binding_context(conn, revision, expected_sha256=revision)
        read_seconds = time.perf_counter() - start
        assert loaded.to_json() == snapshot.to_json()
        from design_graph.model.binding_public_context import project_binding_context

        start = time.perf_counter()
        public = project_binding_context(loaded, unit=unit, region=root.id)
        public_seconds = time.perf_counter() - start
        assert public["contract"] == "binding-public-context/1"
        assert public["evidence"] == "IR_ONLY"
        assert public["initialization"] == public["value"] == "unknown"
        assert "PRIVATE_OTHER_BODY" not in json.dumps(public)
        references = public["references"]
        by_name = [r for r in references if r["name"] == "X" and r["access"] == "read"]
        assert len(by_name) == 2
        assert len({r["target"] for r in by_name}) == 2
        assert sorted(
            len(b["occurrences"]) for b in public["bindings"] if b["name"] == "X"
        ) == [1, 2]
        assert all(r["site"] and r["origin"] and r["identity"] for r in references)
        if os.environ.get("DG_PERSISTENCE_EVIDENCE"):
            out = Path(os.environ["DG_PERSISTENCE_EVIDENCE"])
            (out / "vertical-public.json").write_text(json.dumps(public, indent=2))
            (out / "vertical-metrics.json").write_text(
                json.dumps(
                    {
                        "capture_seconds": capture_seconds,
                        "write_seconds": write_seconds,
                        "reopen_seconds": reopen_seconds,
                        "read_seconds": read_seconds,
                        "public_seconds": public_seconds,
                        "json_bytes": len(snapshot.to_json().encode()),
                        "database_bytes": path.stat().st_size,
                        "revision": revision,
                    },
                    indent=2,
                )
            )
    finally:
        conn.close()
        db.close()
