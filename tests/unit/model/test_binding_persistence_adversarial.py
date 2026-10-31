"""Post-commit Kuzu mutations and independent public-only lookup assertions."""

import json
import os
from dataclasses import replace
from pathlib import Path

import kuzu
import pytest

from design_graph.capture.binding_capture import BindingCapture
from design_graph.model.binding_public_context import project_binding_context
from tests.unit.model.test_binding_persistence import (
    capability,
    cold_read,
    database,
    execute,
    mutate,
    persist,
    snapshot_for,
)

SELECTED = (
    "closure",
    "homonym_copy",
    "functionvar",
    "functionvar_reverse",
    "var_var",
    "simple_alias",
    "destruct_alias",
    "rest_alias",
    "computed",
    "rest_pattern_expression",
    "nested_pattern",
    "utf8",
    "switch",
    "switch_tdz",
)


@pytest.fixture(scope="module")
def cases():
    provider = BindingCapture(
        node=Path(os.environ["DG_CAPTURE_NODE"]),
        toolchain=Path(os.environ["DG_CAPTURE_ENGINE"]),
        fingerprint=os.environ["DG_CAPTURE_FINGERPRINT"],
    )
    fixtures = json.loads(
        (
            Path(__file__).with_name("binding_capture_fixtures") / "fixtures.json"
        ).read_text()
    )
    selected = [f for f in fixtures if f["name"] in SELECTED]
    assert len(selected) == len(SELECTED)
    selected.extend(
        [
            {
                "name": "attack",
                "source": "const X=1;function Probe(p=()=>/*d*/X){let X=2;switch(/*s*/X){case 0:let X=3;return /*c*/X;}return /*b*/X;}function Other(){let X=4;return /*o*/X;}",
            },
            {
                "name": "dynamic_sibling",
                "mode": "script",
                "source": 'let X;function bad(){eval("var X=1");return /*b*/X;}function good(){return /*g*/X;}',
            },
            {
                "name": "same_name_other_unit",
                "source": "let X;function Probe(){return /*b*/X;}",
            },
        ]
    )
    result = {}
    for f in selected:
        capture = provider.capture(
            f["source"].encode(),
            locator=f["name"] + ".js",
            source_type=f.get("mode", "module"),
            syntax="js",
        )
        result[f["name"]] = capture
        if os.environ.get("DG_PERSISTENCE_EVIDENCE"):
            out = Path(os.environ["DG_PERSISTENCE_EVIDENCE"]) / "raw"
            out.mkdir(exist_ok=True)
            (out / (f["name"] + ".json")).write_text(capture.to_json())
    return result


def marked(data, mark):
    source = data["ir"]["units"][0]["source"].encode()
    pos = source.index(("/*" + mark + "*/").encode()) + len(mark) + 4
    ref = next(r for r in data["ir"]["references"] if r["start"] == pos)
    resolution = next(r for r in data["ir"]["resolutions"] if r["id"] == ref["id"])
    return ref, resolution


def public_lookup(public):
    bindings = {
        (b["environment"], b["namespace"], b["name"]): b for b in public["bindings"]
    }
    envs = {e["identity"]: e for e in public["environments"]}
    for ref in public["references"]:
        if ref["state"] == "unknown":
            assert ref["target"] is None
            continue
        cursor = ref["origin"]
        target = None
        path = []
        while cursor is not None:
            path.append(cursor)
            binding = bindings.get((cursor, ref["namespace"], ref["name"]))
            if binding:
                target = binding["identity"]
                break
            cursor = envs[cursor]["outer"]
        assert target == ref["target"]
        assert path == ref["path"]
        assert ref["state"] == ("resolved" if target else "unresolved")
        assert ref["initialization"] == ref["value"] == "unknown"


@pytest.mark.parametrize("name", SELECTED + ("dynamic_sibling",))
def test_faithful_sources_have_exact_occurrences_and_public_lookup(
    tmp_path, cases, name
):
    capture = cases[name]
    snapshot = snapshot_for((capture,))
    path = tmp_path / (name + ".kuzu")
    loaded = cold_read(path, persist(path, snapshot))
    assert loaded.captures[0].to_json() == capture.to_json()
    root = loaded.roots[0]
    public = project_binding_context(loaded, unit=root.unit, region=root.region)
    public_lookup(public)
    if name in SELECTED:
        expected = json.loads(
            (
                Path(__file__).with_name("binding_capture_fixtures")
                / "expectations.json"
            ).read_text()
        )["fixtures"][name]
        raw = json.loads(capture.to_json())
        for marker, spans in expected.items():
            _ref, resolution = marked(raw, marker)
            binding = next(
                b for b in public["bindings"] if b["local_id"] == resolution["target"]
            )
            assert (
                sorted([[o["start"], o["end"]] for o in binding["occurrences"]])
                == spans
            )
    else:
        states = {r["start"]: r["state"] for r in public["references"]}
        raw = json.loads(capture.to_json())
        assert states[marked(raw, "b")[0]["start"]] == "unknown"
        assert states[marked(raw, "g")[0]["start"]] == "resolved"


ATTACKS = (
    "ancestor_target_origin",
    "sibling_target_origin",
    "switch_header_target_origin",
    "reference_sibling_site",
    "site_parent",
    "site_environment",
    "unit_cross",
    "duplicate_binding",
    "duplicate_occurrence",
    "duplicate_root",
    "unknown_proof_kind",
    "unknown_resolution_status",
    "extra_definition_map",
    "missing_logical_version",
    "old_logical_version",
    "unknown_logical_version",
    "old_capture_version",
    "missing_ir_version",
)


def attack(data, kind):
    capture = data["captures"][0]
    ir = capture["ir"]
    body, body_resolution = marked(capture, "b")
    if kind in (
        "ancestor_target_origin",
        "sibling_target_origin",
        "switch_header_target_origin",
    ):
        destination = {
            "ancestor_target_origin": "d",
            "sibling_target_origin": "o",
            "switch_header_target_origin": "c",
        }[kind]
        victim = (
            marked(capture, "s")[1] if kind.startswith("switch") else body_resolution
        )
        candidate = marked(capture, destination)[1]
        for field in ("origin", "target", "path"):
            victim[field] = candidate[field]
    elif kind == "reference_sibling_site":
        body["region"] = marked(capture, "o")[0]["region"]
        body_resolution.update(
            {k: marked(capture, "o")[1][k] for k in ("origin", "target", "path")}
        )
    elif kind == "site_parent":
        next(r for r in ir["regions"] if r["id"] == body["region"])["parent"] = marked(
            capture, "o"
        )[0]["region"]
    elif kind == "site_environment":
        site = next(r for r in ir["regions"] if r["id"] == body["region"])
        site["environment"] = marked(capture, "o")[1]["origin"]
        body_resolution.update(
            {k: marked(capture, "o")[1][k] for k in ("origin", "target", "path")}
        )
    elif kind == "unit_cross":
        body_resolution["unit"] = data["captures"][1]["ir"]["units"][0]["id"]
    elif kind == "duplicate_binding":
        ir["bindings"].append(dict(ir["bindings"][0]))
    elif kind == "duplicate_occurrence":
        ir["occurrences"].append(dict(ir["occurrences"][0]))
    elif kind == "duplicate_root":
        data["roots"].append(dict(data["roots"][0]))
    elif kind == "unknown_proof_kind":
        capture["proofs"] = [
            {
                "kind": "UNRECOGNIZED_ASSERTION",
                "status": "proved",
                "target": body_resolution["target"],
            }
        ]
    elif kind == "unknown_resolution_status":
        body_resolution["state"] = "proved"
    elif kind == "extra_definition_map":
        data["definitions"] = [
            {"binding": body_resolution["target"], "id": "first"},
            {"binding": body_resolution["target"], "id": "second"},
        ]
    elif kind == "missing_logical_version":
        del data["version"]
    elif kind == "old_logical_version":
        data["version"] = "binding-context/0"
    elif kind == "unknown_logical_version":
        data["version"] = "binding-context/999"
    elif kind == "old_capture_version":
        capture["version"] = "binding-capture/1"
    elif kind == "missing_ir_version":
        del ir["version"]
    else:
        raise AssertionError(kind)


@pytest.mark.parametrize("kind", ATTACKS)
def test_real_post_write_mutations_are_refused_before_commitment(tmp_path, cases, kind):
    # Keep capture ordering explicit for mutation selection (canonical order can differ).
    snapshot = snapshot_for((cases["attack"], cases["same_name_other_unit"]))
    path = tmp_path / (kind + ".kuzu")
    revision = persist(path, snapshot)
    data = json.loads(snapshot.to_json())
    data["captures"].sort(key=lambda c: c["ir"]["units"][0]["locator"] != "attack.js")
    attack(data, kind)
    mutate(path, revision, payload=json.dumps(data))
    with pytest.raises(ValueError) as error:
        cold_read(path, revision)
    # Structural/checker refusal, not merely a changed same-DB hash.
    assert "commitment" not in str(error.value)


@pytest.mark.parametrize(
    "format_", [None, "binding-context-kuzu/0", "binding-context-kuzu/999"]
)
def test_physical_version_missing_old_unknown(tmp_path, cases, format_):
    path = tmp_path / "format.kuzu"
    revision = persist(path, snapshot_for((cases["attack"],)))
    mutate(
        path,
        revision,
        query="MATCH (s:BindingContextSnapshot) SET s.format=$format",
        parameters={"format": format_},
    )
    with pytest.raises(ValueError, match="physical.*version"):
        cold_read(path, revision)


def test_absent_extension_is_legacy_unknown_not_upgraded(tmp_path):
    path = tmp_path / "legacy.kuzu"
    db = database(path)
    db.close()
    value = cold_read(path, "0" * 64)
    assert value is None
    assert (
        project_binding_context(value, unit="not-invented", region="not-invented")[
            "availability"
        ]
        == "legacy/unknown"
    )
    db = database(path, True)
    c = kuzu.Connection(db)
    try:
        assert execute(c, "CALL show_tables() RETURN name") == []
    finally:
        c.close()
        db.close()


@pytest.mark.parametrize("budget", ["characters", "records", "depth"])
def test_reader_admits_before_decode_using_real_mutated_database(
    tmp_path, cases, monkeypatch, budget
):
    api = capability()
    path = tmp_path / "budget.kuzu"
    revision = persist(path, snapshot_for((cases["attack"],)))
    payload = {
        "characters": " " * (api.MAX_JSON_CHARS + 1),
        "records": "[" + ",".join("{}" for _ in range(api.MAX_RECORDS + 1)) + "]",
        "depth": "[" * (api.MAX_DEPTH + 1) + "]" * (api.MAX_DEPTH + 1),
    }[budget]
    mutate(path, revision, payload=payload)
    queries = []
    rows = api._rows

    def tracked(conn, query, parameters=None):
        queries.append(query)
        return rows(conn, query, parameters)

    monkeypatch.setattr(api, "_rows", tracked)
    monkeypatch.setattr(
        api.json, "loads", lambda *a, **k: pytest.fail("decoded before admission")
    )
    with pytest.raises(ValueError, match="budget"):
        cold_read(path, revision)
    if budget == "characters":
        assert not any(q.endswith("RETURN s.payload") for q in queries)


def test_permutation_independence_and_no_first_definition(tmp_path, cases):
    snapshot = snapshot_for((cases["attack"], cases["functionvar"]))
    path = tmp_path / "permutation.kuzu"
    revision = persist(path, snapshot)
    data = json.loads(snapshot.to_json())
    data["captures"].reverse()
    data["roots"].reverse()
    for capture in data["captures"]:
        for records in capture["ir"].values():
            if isinstance(records, list):
                records.reverse()
        capture["functions"].reverse()
    mutate(path, revision, payload=json.dumps(data))
    loaded = cold_read(path, revision)
    for root in snapshot.roots:
        projected = project_binding_context(loaded, unit=root.unit, region=root.region)
        assert projected == project_binding_context(
            snapshot, unit=root.unit, region=root.region
        )
        if root.unit == cases["functionvar"].ir.units[0].id:
            assert any(
                b["name"] == "X" and len(b["occurrences"]) == 2
                for b in projected["bindings"]
            )


def test_multi_root_same_name_two_units_qualified_selection(tmp_path, cases):
    api = capability()
    captures = (cases["attack"], cases["same_name_other_unit"])
    roots = tuple(
        api.BindingRoot(
            c.ir.units[0].id,
            next(
                r.id
                for r in c.ir.regions
                if r.slot.value == "function-creation"
                and c.ir.units[0]
                .source.encode()[r.start : r.end]
                .startswith(b"function Probe")
            ),
        )
        for c in captures
    )
    snapshot = api.BindingSnapshot.create("community:two", captures, roots)
    path = tmp_path / "two.kuzu"
    loaded = cold_read(path, persist(path, snapshot))
    for root in roots:
        public = project_binding_context(loaded, unit=root.unit, region=root.region)
        public_lookup(public)
        assert {r["unit"] for r in public["references"]} == {root.unit}
        assert all(r["name"] != "Other" for r in public["references"])
    with pytest.raises(ValueError, match="qualified"):
        project_binding_context(loaded, unit="Probe", region="Probe")


def test_coherent_db_rewrite_is_ir_only_unless_external_digest_matches(tmp_path, cases):
    api = capability()
    original = snapshot_for((cases["attack"],))
    path = tmp_path / "coherent.kuzu"
    old_revision = persist(path, original)
    capture = cases["attack"]
    declaration = next(
        d for d in capture.ir.occurrences if d.name == "X" and d.kind.value == "const"
    )
    forged = replace(
        capture,
        ir=replace(
            capture.ir,
            occurrences=tuple(
                replace(d, start=0, end=capture.ir.units[0].byte_length)
                if d.id == declaration.id
                else d
                for d in capture.ir.occurrences
            ),
        ),
    )
    changed = snapshot_for((forged,))
    payload = changed.to_json()
    new_revision = changed.digest()
    # Kuzu primary keys cannot be SET; a hostile writer can delete/reinsert.
    mutate(path, old_revision, query="MATCH (s:BindingContextSnapshot) DELETE s")
    mutate(
        path,
        old_revision,
        query="CREATE (:BindingContextSnapshot {snapshot_id: $id, format: $format, payload: $payload})",
        parameters={
            "id": new_revision,
            "format": api.PHYSICAL_VERSION,
            "payload": payload,
        },
    )
    loaded = cold_read(path, new_revision)
    assert loaded.to_json() == changed.to_json()
    assert loaded.captures[0].ir.occurrences != original.captures[0].ir.occurrences
    root = loaded.roots[0]
    assert (
        project_binding_context(loaded, unit=root.unit, region=root.region)["evidence"]
        == "IR_ONLY"
    )
    with pytest.raises(ValueError, match="external digest"):
        cold_read(path, new_revision, expected_sha256=old_revision)
    assert (
        cold_read(path, new_revision, expected_sha256=new_revision).digest()
        == new_revision
    )


def test_real_recapture_new_source_kept_original_snapshot(tmp_path, cases):
    provider = BindingCapture(
        node=Path(os.environ["DG_CAPTURE_NODE"]),
        toolchain=Path(os.environ["DG_CAPTURE_ENGINE"]),
        fingerprint=os.environ["DG_CAPTURE_FINGERPRINT"],
    )
    original = cases["same_name_other_unit"]
    new = provider.capture(
        b"let Renamed=42;function Probe(){return Renamed;}",
        locator=original.ir.units[0].locator,
        source_type="module",
        syntax="js",
    )
    path = tmp_path / "recapture.kuzu"
    old_snapshot, new_snapshot = snapshot_for((original,)), snapshot_for((new,))
    old_revision = persist(path, old_snapshot)
    new_revision = persist(path, new_snapshot)
    assert old_revision != new_revision
    assert (
        cold_read(path, old_revision, expected_sha256=old_revision).to_json()
        == old_snapshot.to_json()
    )
    assert (
        cold_read(path, new_revision, expected_sha256=new_revision).to_json()
        == new_snapshot.to_json()
    )
    with pytest.raises(ValueError, match="external digest"):
        cold_read(path, new_revision, expected_sha256=old_revision)


def test_duplicate_write_rolled_back_and_connection_reusable(tmp_path, cases):
    api = capability()
    snapshot = snapshot_for((cases["attack"],))
    path = tmp_path / "rollback.kuzu"
    revision = persist(path, snapshot)
    db = database(path)
    conn = kuzu.Connection(db)
    try:
        with pytest.raises(RuntimeError, match="primary key|duplicate"):
            api.write_binding_context(conn, snapshot)
        assert api.read_binding_context(conn, revision).digest() == revision
    finally:
        conn.close()
        db.close()
