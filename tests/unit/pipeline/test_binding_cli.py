"""Normal entry points, real capture/Kuzu; no dirty worktree bytes required."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not all(
        os.environ.get(key)
        for key in ("DG_CAPTURE_NODE", "DG_CAPTURE_ENGINE", "DG_CAPTURE_FINGERPRINT")
    ),
    reason="requires explicitly prepared reviewed binding engine and Node",
)

SOURCE = """const X = 9;
function empty() {}
function defaults(p = () => X) { var X = 2; return [p, X]; }
function merge() { function f() {} var f; return f; }
function switches() { switch (X) { case 0: const X = 1; return X; } }
"""


def cli(module, args, *, cold=False, before=""):
    guard = (
        """
import importlib.abc, sys, subprocess
class Refuse(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, *args):
  if fullname.startswith('design_graph.capture') or (fullname.startswith('design_graph.') and 'parsing' in fullname):
   raise AssertionError('retrieval imported capture/parser: '+fullname)
sys.meta_path.insert(0, Refuse())
def forbidden(*a, **k): raise AssertionError('retrieval launched subprocess')
subprocess.Popen = forbidden
"""
        if cold
        else ""
    )
    audit = """
import atexit, hashlib, json, os, pathlib
def audit_imports():
 if 'DG_PERSISTENCE_EVIDENCE' not in os.environ: return
 out = pathlib.Path(os.environ['DG_PERSISTENCE_EVIDENCE'])
 expected = json.loads((out/'snapshot-hashes.json').read_text())
 root = out/'snapshot'
 imported = {}
 for name, module in list(sys.modules.items()):
  if name.startswith('design_graph') and getattr(module, '__file__', None):
   path = pathlib.Path(module.__file__).resolve()
   relative = str(path.relative_to(root))
   digest = hashlib.sha256(path.read_bytes()).hexdigest()
   assert expected[relative] == digest, ('non-frozen product import', path)
   imported[relative] = digest
 with (out/'cli-imports.jsonl').open('a') as stream:
  stream.write(json.dumps({'argv':sys.argv, 'imports':imported})+'\\n')
atexit.register(audit_imports)
"""
    code = (
        "import sys\n"
        + guard
        + audit
        + before
        + f"\nfrom {module} import main\nmain()\n"
    )
    env = dict(os.environ, PATH="/no-node" if cold else os.environ["PATH"])
    result = subprocess.run(
        [sys.executable, "-B", "-c", code, *map(str, args)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=45,
    )
    if os.environ.get("DG_PERSISTENCE_EVIDENCE"):
        evidence = Path(os.environ["DG_PERSISTENCE_EVIDENCE"]) / "cli-raw.jsonl"
        with evidence.open("a") as stream:
            stream.write(
                json.dumps(
                    {
                        "module": module,
                        "args": list(map(str, args)),
                        "cold": cold,
                        "returncode": result.returncode,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    }
                )
                + "\n"
            )
    assert "Exception ignored in atexit" not in result.stderr, result.stderr
    return result


def build(source, db, *extra, before=""):
    return cli(
        "design_graph.interface.cli.build",
        [
            source,
            "--db",
            db,
            "--json",
            "--binding-node",
            os.environ["DG_CAPTURE_NODE"],
            "--binding-engine",
            os.environ["DG_CAPTURE_ENGINE"],
            "--binding-fingerprint",
            os.environ["DG_CAPTURE_FINGERPRINT"],
            *extra,
        ],
        before=before,
    )


def query(db, revision, unit, region):
    return cli(
        "design_graph.interface.cli.query",
        [
            "binding-context",
            "--db",
            db,
            "--snapshot",
            revision,
            "--unit",
            unit,
            "--region",
            region,
        ],
        cold=True,
    )


def test_normal_build_reopened_cold_public_multi_root(tmp_path):
    html = tmp_path / "small.html"
    html.write_text(
        "<!DOCTYPE html><html><head><title>Small</title></head><body>"
        "<main><h1>Small</h1></main><script>" + SOURCE + "</script>"
        '<script type="module">const X = 3; function empty() { return X; }</script>'
        "</body></html>"
    )
    db = tmp_path / "new.db"
    built = build(html, db)
    assert built.returncode == 0, built.stderr
    result = json.loads(built.stdout)
    assert result["status"] == "built"
    assert result["write_errors"] == 0
    assert (
        result["screens"] >= 1
    )  # existing general model was not replaced by a ledger harness
    manifest = json.loads(Path(str(db) + ".binding.json").read_text())
    assert len(manifest["units"]) == 2
    roots = manifest["roots"]
    assert len(roots) >= 8
    public = []
    for root in roots:
        read = query(db, manifest["snapshot"], root["unit"], root["region"])
        assert read.returncode == 0, read.stderr
        row = json.loads(read.stdout)
        assert row["contract"] == "binding-public-context/1"
        assert row["evidence"] == "IR_ONLY"
        assert row["initialization"] == row["value"] == "unknown"
        assert row["source"]["unit"] == root["unit"]
        original = next(
            unit
            for unit in manifest["units"]
            if unit["locator"] == row["source"]["locator"]
        )
        assert row["source"]["sha256"] == original["source_sha256"]
        assert row["source"]["byte_length"] == original["byte_length"]
        assert "source_code" not in row and "body" not in row["source"]
        public.append(row)
    empty = [row for row in public if not row["references"]]
    assert empty and all(row["sites"] and row["environments"] for row in empty)
    assert len({row["root"]["identity"] for row in public}) == len(public)
    same_local_root = [row for row in public if row["root"]["local_region"] == "r0"]
    assert len(same_local_root) == 2
    assert (
        same_local_root[0]["source"]["sha256"] != same_local_root[1]["source"]["sha256"]
    )
    identities = [
        {binding["identity"] for binding in row["bindings"]} for row in same_local_root
    ]
    assert identities[0] and identities[1] and identities[0].isdisjoint(identities[1])
    refused = query(db, manifest["snapshot"], "u:missing", roots[0]["region"])
    assert refused.returncode != 0 and not refused.stdout
    assert any(
        len(binding["occurrences"]) == 2
        for row in public
        for binding in row["bindings"]
    )
    skipped = build(html, db)
    assert skipped.returncode == 0, skipped.stderr
    assert json.loads(skipped.stdout)["status"] == "skipped"
