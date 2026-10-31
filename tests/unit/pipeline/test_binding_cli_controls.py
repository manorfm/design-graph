"""Bounded real consumer and pipeline rejection controls."""

import base64
import json
from hashlib import sha256
from pathlib import Path

import kuzu

from tests.unit.pipeline.test_binding_cli import build, query


def html_source(tmp_path, script="const X = 1; function empty() {}"):
    path = tmp_path / "fixture.html"
    path.write_text(
        "<!DOCTYPE html><html><body><main>Fixture</main><script>"
        + script
        + "</script></body></html>"
    )
    return path


def open_db(path):
    db = kuzu.Database(str(path), buffer_pool_size=128 * 1024 * 1024, max_num_threads=2)
    return db, kuzu.Connection(db)


def test_existing_destination_and_changed_source_preserved(tmp_path):
    source = html_source(tmp_path)
    db = tmp_path / "first.db"
    first = build(source, db)
    assert first.returncode == 0, first.stderr
    protected = [db, Path(str(db) + ".state.json"), Path(str(db) + ".binding.json")]
    before = [sha256(p.read_bytes()).hexdigest() for p in protected]
    source.write_text(source.read_text().replace("X = 1", "X = 2"))
    failed = build(source, db)
    assert failed.returncode != 0 and "new destination" in failed.stderr
    assert [sha256(p.read_bytes()).hexdigest() for p in protected] == before
    second = tmp_path / "second.db"
    assert build(source, second).returncode == 0
    assert (
        json.loads(Path(str(second) + ".binding.json").read_text())["snapshot"]
        != json.loads(protected[-1].read_text())["snapshot"]
    )


def test_legacy_and_partial_schema_through_cold_consumer(tmp_path):
    db = tmp_path / "legacy.db"
    database, connection = open_db(db)
    connection.execute("CREATE NODE TABLE Legacy(id STRING PRIMARY KEY)").close()
    connection.close()
    database.close()
    legacy = query(db, "0" * 64, "u:unknown", "r0")
    assert legacy.returncode == 0, legacy.stderr
    result = json.loads(legacy.stdout)
    assert result["availability"] == "legacy/unknown"
    assert result["evidence"] == "legacy"
    database, connection = open_db(db)
    connection.execute(
        "CREATE NODE TABLE BindingContextSnapshot(snapshot_id STRING PRIMARY KEY)"
    ).close()
    connection.close()
    database.close()
    partial = query(db, "0" * 64, "u:unknown", "r0")
    assert partial.returncode != 0
    assert "partial or incompatible" in partial.stderr and not partial.stdout


def test_postpersist_version_mutation_refused_by_actual_consumer(tmp_path):
    source = html_source(tmp_path)
    db = tmp_path / "mutation.db"
    assert build(source, db).returncode == 0
    manifest = json.loads(Path(str(db) + ".binding.json").read_text())
    root = manifest["roots"][0]
    assert query(db, manifest["snapshot"], root["unit"], root["region"]).returncode == 0
    database, connection = open_db(db)
    connection.execute(
        "MATCH (s:BindingContextSnapshot) SET s.format='unknown'"
    ).close()
    connection.close()
    database.close()
    refused = query(db, manifest["snapshot"], root["unit"], root["region"])
    assert refused.returncode != 0 and not refused.stdout
    assert "unsupported physical" in refused.stderr


def test_bundle_whole_units_and_explicit_option_omissions(tmp_path):
    js = b"const X = 4; function empty() { return X; }\n"
    manifest = {
        "app": {
            "mime": "application/javascript",
            "data": base64.b64encode(js).decode(),
        },
        "unused": {
            "mime": "application/javascript",
            "data": base64.b64encode(b"const Y=0;").decode(),
        },
    }
    template = '<!DOCTYPE html><html><body><main>App</main><script src="app"></script><script type="text/jsx">const Z = <div/>;</script><script type="text/babel" data-type="module">export const Bad = 1;</script><script type="application/json">{}</script><script src="https://not-fetched.invalid/a.js"></script></body></html>'
    html = tmp_path / "bundle.html"
    html.write_text(
        '<!DOCTYPE html><html><body><script type="__bundler/manifest">'
        + json.dumps(manifest)
        + '</script><script type="__bundler/template">'
        + json.dumps(template).replace("</", "<\\/")
        + "</script></body></html>"
    )
    db = tmp_path / "bundle.db"
    built = build(html, db)
    assert built.returncode == 0, built.stderr
    result = json.loads(Path(str(db) + ".binding.json").read_text())
    assert len(result["units"]) == 2
    assert result["units"][0]["source_sha256"] == sha256(js).hexdigest()
    assert result["units"][0]["byte_length"] == len(js)
    assert result["units"][1]["syntax"] == "jsx"
    excluded = {r["reason"] for r in result["coverage"] if r["status"] == "excluded"}
    assert excluded >= {
        "unsupported-script-options",
        "unsupported-script-type",
        "external-script-not-fetched",
        "unreferenced-bundle-entry",
        "bundle-container-not-program",
    }
