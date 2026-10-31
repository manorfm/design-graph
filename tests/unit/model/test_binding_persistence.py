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
from design_graph.model.binding_public_context import project_binding_context


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


def snapshot_for(captures):
    api = capability()
    return api.BindingSnapshot.create(
        "community:test",
        captures,
        tuple(
            api.BindingRoot(c.ir.units[0].id, c.ir.units[0].root_region)
            for c in captures
        ),
    )


def execute(conn, query, parameters=None):
    result = conn.execute(query, parameters or {})
    try:
        return result.get_all()
    finally:
        result.close()


def persist(path, snapshot):
    db = database(path)
    conn = kuzu.Connection(db)
    try:
        return capability().write_binding_context(conn, snapshot)
    finally:
        conn.close()
        db.close()


def mutate(path, revision, *, payload=None, query=None, parameters=None):
    db = database(path)
    conn = kuzu.Connection(db)
    try:
        if payload is not None:
            execute(
                conn,
                "MATCH (s:BindingContextSnapshot) WHERE s.snapshot_id=$id SET s.payload=$payload",
                {"id": revision, "payload": payload},
            )
            assert execute(
                conn,
                "MATCH (s:BindingContextSnapshot) WHERE s.snapshot_id=$id RETURN s.payload",
                {"id": revision},
            ) == [[payload]]
        if query:
            execute(conn, query, parameters)
    finally:
        conn.close()
        db.close()


def cold_read(path, revision, **kwargs):
    db = database(path, True)
    conn = kuzu.Connection(db)
    try:
        return capability().read_binding_context(conn, revision, **kwargs)
    finally:
        conn.close()
        db.close()


def test_physical_extra_column_fails_closed(tmp_path, captured):
    path = tmp_path / "extra.kuzu"
    revision = persist(path, snapshot_for((captured[0],)))
    mutate(
        path, revision, query="ALTER TABLE BindingContextSnapshot ADD surprise STRING"
    )
    with pytest.raises(ValueError, match="schema"):
        cold_read(path, revision)


def test_partial_schema_kept_original_operational_error(tmp_path):
    path = tmp_path / "partial.kuzu"
    db = database(path)
    conn = kuzu.Connection(db)
    try:
        execute(
            conn,
            "CREATE NODE TABLE BindingContextSnapshot(snapshot_id STRING PRIMARY KEY)",
        )
    finally:
        conn.close()
        db.close()
    with pytest.raises(ValueError, match="schema"):
        cold_read(path, "0" * 64)


def test_public_provenance_has_no_dangling_links(tmp_path, captured):
    snapshot = snapshot_for((captured[0],))
    path = tmp_path / "public.kuzu"
    loaded = cold_read(path, persist(path, snapshot))
    root = snapshot.roots[0]
    public = project_binding_context(loaded, unit=root.unit, region=root.region)
    envs = {e["identity"] for e in public["environments"]}
    sites = {s["identity"] for s in public["sites"]}
    for site in public["sites"]:
        assert site["parent"] is None or site["parent"] in sites
        assert site["environment"] is None or site["environment"] in envs
    for env in public["environments"]:
        assert env["owner"] in sites
        assert env["outer"] is None or env["outer"] in envs


def test_fresh_reader_process_without_capture_import_or_subprocess(tmp_path, captured):
    import sys

    snapshot = snapshot_for((captured[0],))
    root = snapshot.roots[0]
    path = tmp_path / "fresh.kuzu"
    revision = persist(path, snapshot)
    code = """
import builtins,json,subprocess,sys
original = builtins.__import__
def guarded(name,*a,**k):
    if name == 'design_graph.capture' or name.startswith('design_graph.capture.'):
        raise AssertionError('reader imported parser/capture provider')
    return original(name,*a,**k)
builtins.__import__=guarded
def refused(*a,**k):
    raise AssertionError('reader launched subprocess')
subprocess.Popen=refused
import kuzu
from design_graph.model.graph.binding_context import read_binding_context
from design_graph.model.binding_public_context import project_binding_context
db=kuzu.Database(sys.argv[1],buffer_pool_size=128*1024*1024,max_num_threads=2,read_only=True)
c=kuzu.Connection(db)
try:
    value=read_binding_context(c,sys.argv[2],expected_sha256=sys.argv[2])
    public=project_binding_context(value,unit=sys.argv[3],region=sys.argv[4])
    assert public['evidence']=='IR_ONLY'
    assert not any(n.startswith('design_graph.capture.') for n in sys.modules)
    print(json.dumps(public,sort_keys=True))
finally:
    c.close();db.close()
"""
    proc = subprocess.run(
        [sys.executable, "-B", "-c", code, str(path), revision, root.unit, root.region],
        env={
            **os.environ,
            "PATH": "/node-is-not-installed",
            "DG_CAPTURE_NODE": "/absent/node",
        },
        capture_output=True,
        check=False,
        text=True,
        timeout=20,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == project_binding_context(
        snapshot, unit=root.unit, region=root.region
    )
    if os.environ.get("DG_PERSISTENCE_EVIDENCE"):
        out = Path(os.environ["DG_PERSISTENCE_EVIDENCE"])
        (out / "cold-reader.py").write_text(code)
        (out / "cold-reader-public.json").write_text(proc.stdout)


def test_empty_function_root_closes_environment_provenance(tmp_path, captured):
    api = capability()
    capture = captured[0]
    unit = capture.ir.units[0]
    root = next(
        r
        for r in capture.ir.regions
        if r.slot.value == "function-creation"
        and unit.source.encode()[r.start : r.end].startswith(b"function X")
    )
    snapshot = api.BindingSnapshot.create(
        "community:empty", (capture,), (api.BindingRoot(unit.id, root.id),)
    )
    path = tmp_path / "empty-root.kuzu"
    public = project_binding_context(
        cold_read(path, persist(path, snapshot)), unit=unit.id, region=root.id
    )
    assert public["references"] == []
    envs = {e["identity"] for e in public["environments"]}
    assert envs
    assert all(
        s["environment"] is None or s["environment"] in envs for s in public["sites"]
    )


def test_public_never_slices_arbitrary_occurrence_as_source(tmp_path, captured):
    from dataclasses import replace

    capture = captured[0]
    unit = capture.ir.units[0]
    # An internally coherent but hostile occurrence span is not syntax proof.
    # Never turn such a span into another root's body in the public response.
    declaration = next(
        d for d in capture.ir.occurrences if d.name == "X" and d.kind.value == "const"
    )
    altered = replace(declaration, start=0, end=unit.byte_length)
    changed = replace(
        capture,
        ir=replace(
            capture.ir,
            occurrences=tuple(
                altered if d.id == declaration.id else d for d in capture.ir.occurrences
            ),
        ),
    )
    snapshot = snapshot_for((changed,))
    path = tmp_path / "no-source-slice.kuzu"
    loaded = cold_read(path, persist(path, snapshot))
    root = snapshot.roots[0]
    public = project_binding_context(loaded, unit=root.unit, region=root.region)
    assert "PRIVATE_OTHER_BODY" not in json.dumps(public)
