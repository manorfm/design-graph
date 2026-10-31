"""Real normal CLI catch capture, cold projection and post-persist refusal."""

import json
import os
from pathlib import Path

import pytest

from tests.unit.pipeline.test_binding_cli import build, query
from tests.unit.pipeline.test_binding_cli import pytestmark as prepared_engine_mark
from tests.unit.pipeline.test_binding_cli_controls import open_db

pytestmark = prepared_engine_mark


def test_catch_static_cells_survived_normal_build_and_cold_read(tmp_path):
    source = tmp_path / "catch.html"
    source.write_text(
        "<html><body><main>Catch</main><script>"
        "throw new Error('SOURCE_MUST_NOT_EXECUTE');process.exit(91);"
        "const x=9;function f(p=()=>x){var x;"
        "try{}catch({x=()=>x}){let local;()=>x;()=>local;}"
        "try{}catch(x){var x=1;()=>x;}return x;}"
        "</script></body></html>"
    )
    db = tmp_path / "catch.db"
    built = build(source, db)
    assert built.returncode == 0, built.stderr
    built_result = json.loads(built.stdout)
    assert built_result["screens"] >= 1 and built_result["write_errors"] == 0
    manifest = json.loads(Path(str(db) + ".binding.json").read_text())
    assert manifest["contract"] == "binding-build/4"
    assert manifest["coverage"][0]["status"] == "captured"
    root = next(r for r in manifest["roots"] if r["region"] == "r0")
    read = query(db, manifest["snapshot"], root["unit"], root["region"])
    assert read.returncode == 0, read.stderr
    public = json.loads(read.stdout)
    assert public["evidence"] == "IR_ONLY"
    assert public["initialization"] == public["value"] == "unknown"
    xs = [b for b in public["bindings"] if b["name"] == "x"]
    assert len(xs) == len({b["environment"] for b in xs}) == 4
    caught = [b for b in xs if any(d["kind"] == "parameter" for d in b["occurrences"])]
    assert len(caught) == 2
    assert all(len(b["occurrences"]) == 1 for b in caught)
    assert all(
        r["initialization"] == r["value"] == "unknown" for r in public["references"]
    )
    assert all(r["origin"] and r["site"] for r in public["references"])
    reused = build(source, db)
    assert reused.returncode == 0, reused.stderr
    assert json.loads(reused.stdout)["status"] == "skipped"
    database, connection = open_db(db)
    try:
        revision = manifest["snapshot"]
        result = connection.execute(
            "MATCH (s:BindingContextSnapshot) WHERE s.snapshot_id=$id RETURN s.payload",
            {"id": revision},
        )
        payload = json.loads(result.get_next()[0])
        result.close()
        payload["captures"][0]["ir"]["resolutions"][0]["origin"] = "e:forged"
        raw = json.dumps(payload)
        connection.execute(
            "MATCH (s:BindingContextSnapshot) WHERE s.snapshot_id=$id SET s.payload=$payload",
            {"id": revision, "payload": raw},
        ).close()
        result = connection.execute(
            "MATCH (s:BindingContextSnapshot) WHERE s.snapshot_id=$id RETURN s.payload",
            {"id": revision},
        )
        assert result.get_next()[0] == raw
        result.close()
    finally:
        connection.close()
        database.close()
    refused = query(db, revision, root["unit"], root["region"])
    assert refused.returncode != 0 and not refused.stdout
    if os.environ.get("DG_PERSISTENCE_EVIDENCE"):
        out = Path(os.environ["DG_PERSISTENCE_EVIDENCE"])
        (out / "catch-cli-manifest.json").write_text(json.dumps(manifest, indent=2))
        (out / "catch-cold-public.json").write_text(read.stdout)
        (out / "catch-cli-proof.json").write_text(
            json.dumps(
                {
                    "build": built_result,
                    "reuse": json.loads(reused.stdout),
                    "corruption_returncode": refused.returncode,
                    "corruption_stderr": refused.stderr,
                    "mutation_readback": True,
                    "database_deliberately_corrupted": str(db),
                },
                indent=2,
            )
        )


@pytest.mark.parametrize(
    "mutation", ["owner", "origin", "site", "cross-unit", "old-profile"]
)
def test_catch_persisted_typed_edits_refused_cold_retrieval(tmp_path, mutation):
    source = tmp_path / "typed.html"
    source.write_text(
        "<html><body><main>Typed</main><script>let x;try{}catch(x){()=>x;}</script></body></html>"
    )
    db = tmp_path / "typed.db"
    built = build(source, db)
    assert built.returncode == 0, built.stderr
    manifest = json.loads(Path(str(db) + ".binding.json").read_text())
    root = next(r for r in manifest["roots"] if r["region"] == "r0")
    positive = query(db, manifest["snapshot"], root["unit"], root["region"])
    assert positive.returncode == 0, positive.stderr
    assert json.loads(positive.stdout)["evidence"] == "IR_ONLY"
    database, connection = open_db(db)
    try:
        revision = manifest["snapshot"]
        result = connection.execute(
            "MATCH (s:BindingContextSnapshot) WHERE s.snapshot_id=$id RETURN s.payload",
            {"id": revision},
        )
        payload = json.loads(result.get_next()[0])
        result.close()
        captured = payload["captures"][0]
        ir = captured["ir"]
        caught = next(r for r in ir["regions"] if r["slot"] == "catch")
        assert any(
            d["kind"] == "parameter" and d["environment"] == caught["environment"]
            for d in ir["occurrences"]
        )
        if mutation == "owner":
            caught["slot"] = "block"
        elif mutation == "origin":
            ir["resolutions"][0]["origin"] = ir["environments"][0]["id"]
        elif mutation == "site":
            body = next(r for r in ir["regions"] if r["slot"] == "catch-body")
            body["parent"] = ir["units"][0]["root_region"]
        elif mutation == "cross-unit":
            caught["unit"] = "u:other"
        else:
            captured["version"] = "binding-capture/2"
            ir["version"], ir["profile"] = "binding-ir/2", "static-unit-chain/2"
        raw = json.dumps(payload)
        connection.execute(
            "MATCH (s:BindingContextSnapshot) WHERE s.snapshot_id=$id SET s.payload=$payload",
            {"id": revision, "payload": raw},
        ).close()
        result = connection.execute(
            "MATCH (s:BindingContextSnapshot) WHERE s.snapshot_id=$id RETURN s.payload",
            {"id": revision},
        )
        assert result.get_next()[0] == raw
        result.close()
    finally:
        connection.close()
        database.close()
    refused = query(db, revision, root["unit"], root["region"])
    assert refused.returncode != 0 and not refused.stdout
    stale = build(source, db)
    assert stale.returncode != 0 and not stale.stdout
