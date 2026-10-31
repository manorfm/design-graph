"""Real normal CLI loop capture, persisted projection and cold corruption refusal."""

import json
from pathlib import Path

from tests.unit.pipeline.test_binding_cli import build, query
from tests.unit.pipeline.test_binding_cli import pytestmark as prepared_engine_mark
from tests.unit.pipeline.test_binding_cli_controls import open_db

pytestmark = prepared_engine_mark


def test_loop_static_cells_survived_normal_build_and_cold_read(tmp_path):
    source = tmp_path / "loops.html"
    source.write_text(
        "<html><body><main>Loops</main><script>"
        "const x=9;function f(p=()=>x){var x;"
        "for(let x=0;x<2;x++){()=>x;}"
        "for(const x of [1]){()=>x;}return x;}"
        "</script></body></html>"
    )
    db = tmp_path / "loops.db"
    built = build(source, db)
    assert built.returncode == 0, built.stderr
    assert json.loads(built.stdout)["screens"] >= 1
    manifest = json.loads(Path(str(db) + ".binding.json").read_text())
    assert manifest["coverage"][0]["status"] == "captured"
    root = next(r for r in manifest["roots"] if r["region"] == "r0")
    read = query(db, manifest["snapshot"], root["unit"], root["region"])
    assert read.returncode == 0, read.stderr
    public = json.loads(read.stdout)
    assert public["evidence"] == "IR_ONLY"
    assert public["initialization"] == public["value"] == "unknown"
    xs = [b for b in public["bindings"] if b["name"] == "x"]
    assert len(xs) == 4
    assert len({b["environment"] for b in xs}) == 4
    assert all(
        r["initialization"] == r["value"] == "unknown" for r in public["references"]
    )
    assert all(r["origin"] and r["site"] for r in public["references"])
    # Mutate only this new test DB, read back the exact write, then cold CLI.
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
