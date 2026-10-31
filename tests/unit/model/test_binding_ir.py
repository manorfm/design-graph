"""Synthetic IR controls, not parser/capture or database integration tests."""

import importlib
import importlib.util
import json


def core():
    assert importlib.util.find_spec("design_graph.model.binding_ir") is not None, (
        "standalone versioned binding IR is not implemented"
    )
    return importlib.import_module("design_graph.model.binding_ir")


def empty_payload():
    return {
        "version": "binding-ir/1",
        "profile": "lexical-chain/1",
        "units": [],
        "environments": [],
        "regions": [],
        "occurrences": [],
        "bindings": [],
        "references": [],
        "resolutions": [],
    }


def test_versioned_transport_roundtrip():
    m = core()
    payload = empty_payload()
    envelope = m.Envelope.from_json(json.dumps(payload))
    assert json.loads(envelope.to_json()) == payload
    assert m.Envelope.from_json(envelope.to_json()) == envelope


from copy import deepcopy
from dataclasses import asdict, replace

import pytest


def occurrence(kind, id="d", name="x", namespace="value", environment="vars", unit="u"):
    m = core()
    return m.DeclarationOccurrence(
        id,
        unit,
        environment,
        m.Namespace(namespace),
        name,
        m.DeclarationKind(kind),
        0,
        1,
    )


def environment(kind="function-var", id="vars", unit="u"):
    m = core()
    return m.Environment(id, unit, m.EnvironmentKind(kind), "body", None, True)


@pytest.mark.parametrize(
    "kinds", [("function", "var"), ("var", "function"), ("var", "var")]
)
def test_canonical_binding_preserves_permitted_occurrences_in_any_order(kinds):
    m = core()
    ds = tuple(occurrence(k, str(i)) for i, k in enumerate(kinds))
    bs = m.canonical_bindings((environment(),), ds)
    assert len(bs) == 1
    assert bs[0].occurrences == ("0", "1")
    assert m.canonical_bindings((environment(),), tuple(reversed(ds))) == bs
    assert bs[0].id not in {d.id for d in ds}


@pytest.mark.parametrize(
    "kinds", [("let", "let"), ("const", "var"), ("function", "function")]
)
def test_unmodeled_or_illegal_declaration_coexistence_is_rejected(kinds):
    m = core()
    with pytest.raises(ValueError):
        m.canonical_bindings(
            (environment(),), tuple(occurrence(k, str(i)) for i, k in enumerate(kinds))
        )


def test_binding_identity_is_unit_environment_and_namespace_qualified():
    m = core()
    ds = (
        occurrence("var"),
        occurrence("var", "d2", unit="other"),
        occurrence("var", "d3", namespace="type"),
    )
    # Type-space declarations are outside the finite JS runtime profile.
    with pytest.raises(ValueError):
        m.canonical_bindings((environment(), environment(unit="other")), ds)
    bs = m.canonical_bindings((environment(), environment(unit="other")), ds[:2])
    assert len({b.id for b in bs}) == 2


def region(
    id,
    slot,
    parent=None,
    environment=None,
    start=0,
    end=200,
    split=None,
    unit="u",
    complete=True,
):
    return {
        "id": id,
        "unit": unit,
        "slot": slot,
        "parent": parent,
        "environment": environment,
        "start": start,
        "end": end,
        "split_parameters": split,
        "complete": complete,
    }


def switch_payload():
    import hashlib

    p = empty_payload()
    source = "x" * 200
    p["units"] = [
        {
            "id": "u",
            "locator": "synthetic.js",
            "source": source,
            "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "byte_length": 200,
            "root_region": "root",
        }
    ]
    p["environments"] = [
        {
            "id": "outer",
            "unit": "u",
            "kind": "root",
            "owner": "root",
            "outer": None,
            "complete": True,
        },
        {
            "id": "case",
            "unit": "u",
            "kind": "case",
            "owner": "cases",
            "outer": "outer",
            "complete": True,
        },
    ]
    p["regions"] = [
        region("root", "root", environment="outer"),
        region("sw", "switch", "root"),
        region("disc", "switch-discriminant", "sw", start=10, end=11),
        region("cases", "switch-case", "sw", "case", start=20, end=190),
    ]
    p["occurrences"] = [
        {
            "id": "outer-x",
            "unit": "u",
            "environment": "outer",
            "namespace": "value",
            "name": "x",
            "kind": "const",
            "start": 0,
            "end": 1,
        },
        {
            "id": "case-x",
            "unit": "u",
            "environment": "case",
            "namespace": "value",
            "name": "x",
            "kind": "let",
            "start": 30,
            "end": 31,
        },
    ]
    p["references"] = [
        {
            "id": "disc-x",
            "unit": "u",
            "region": "disc",
            "namespace": "value",
            "name": "x",
            "access": "read",
            "start": 10,
            "end": 11,
        },
        {
            "id": "case-read",
            "unit": "u",
            "region": "cases",
            "namespace": "value",
            "name": "x",
            "access": "read",
            "start": 25,
            "end": 26,
        },
    ]
    fill_bindings(p)
    targets = {b["environment"]: b["id"] for b in p["bindings"]}
    p["resolutions"] = [
        {
            "id": "disc-x",
            "unit": "u",
            "state": "resolved",
            "origin": "outer",
            "target": targets["outer"],
            "path": ["outer"],
        },
        {
            "id": "case-read",
            "unit": "u",
            "state": "resolved",
            "origin": "case",
            "target": targets["case"],
            "path": ["case"],
        },
    ]
    return p


def fill_bindings(p):
    m = core()
    es = tuple(
        m.Environment(**{**e, "kind": m.EnvironmentKind(e["kind"])})
        for e in p["environments"]
    )
    ds = tuple(
        m.DeclarationOccurrence(
            **{
                **d,
                "namespace": m.Namespace(d["namespace"]),
                "kind": m.DeclarationKind(d["kind"]),
            }
        )
        for d in p["occurrences"]
    )
    p["bindings"] = [asdict(b) for b in m.canonical_bindings(es, ds)]


def admit(p):
    return core().Envelope.from_json(json.dumps(p))


def test_switch_origin_and_tdz_do_not_use_target_as_oracle():
    e = admit(switch_payload())
    result = e.check()
    assert [r.origin for r in result.resolutions] == ["case", "outer"]
    assert all(r.state.value == "resolved" for r in result.resolutions)
    assert result.initialization.value == "unknown"
    assert result.value.value == "unknown"
    assert result.evidence.value == "ir-only"
    assert admit(json.loads(e.to_json())).to_json() == e.to_json()


@pytest.mark.parametrize(
    "mutation",
    [
        "scope+target",
        "target-only",
        "wrong-occurrence",
        "wrong-root",
        "wrong-unit",
        "cycle",
        "inventory",
        "region-cycle",
        "extra-resolution",
        "missing-resolution",
        "wrong-owner",
    ],
)
def test_targeted_corruptions_fail_closed(mutation):
    p = switch_payload()
    r = p["resolutions"][0]
    if mutation == "scope+target":
        r.update(origin="case", target=p["resolutions"][1]["target"], path=["case"])
    elif mutation == "target-only":
        r["target"] = p["resolutions"][1]["target"]
    elif mutation == "wrong-occurrence":
        p["bindings"][0]["occurrences"] = ["case-x", "outer-x"]
    elif mutation == "wrong-root":
        p["units"][0]["root_region"] = "cases"
    elif mutation == "wrong-unit":
        p["references"][0]["unit"] = "other"
    elif mutation == "cycle":
        p["environments"][0]["outer"] = "case"
    elif mutation == "inventory":
        p["bindings"] = p["bindings"][:1]
    elif mutation == "region-cycle":
        p["regions"][1]["parent"] = "disc"
    elif mutation == "extra-resolution":
        p["resolutions"].append({**r, "id": "absent"})
    elif mutation == "missing-resolution":
        p["resolutions"].pop()
    elif mutation == "wrong-owner":
        p["environments"][1]["owner"] = "disc"
    with pytest.raises(ValueError):
        admit(p)


def test_incomplete_outer_inventory_does_not_poison_proven_inner_reference():
    p = switch_payload()
    p["environments"][0]["complete"] = False
    p["resolutions"][0].update(state="unknown", target=None)
    assert [r.state.value for r in admit(p).check().resolutions] == [
        "resolved",
        "unknown",
    ]


def test_unknown_region_is_local_not_unit_wide():
    p = switch_payload()
    p["regions"][2]["complete"] = False
    p["resolutions"][0].update(state="unknown", target=None, path=[])
    assert [r.state.value for r in admit(p).check().resolutions] == [
        "resolved",
        "unknown",
    ]


def test_unresolved_is_distinct_from_unknown():
    p = switch_payload()
    p["references"][0]["name"] = "absent"
    p["resolutions"][0].update(state="unresolved", target=None)
    assert admit(p).check().resolutions[1].state.value == "unresolved"


def test_permutation_does_not_change_canonical_transport():
    p = switch_payload()
    first = admit(p).to_json()
    for field in (
        "units",
        "environments",
        "regions",
        "occurrences",
        "bindings",
        "references",
        "resolutions",
    ):
        p[field].reverse()
    assert admit(p).to_json() == first


def function_payload(split=True, closure=True):
    p = switch_payload()
    p["regions"] = [
        region("root", "root", environment="outer"),
        region("fn", "function-creation", "root", split=split),
        region("parameters", "function-parameters", "fn", "params", end=90),
        region("body", "function-body", "fn", "vars" if split else None, start=90),
    ]
    p["environments"] = p["environments"][:1] + [
        {
            "id": "params",
            "unit": "u",
            "kind": "parameters" if split else "function-shared",
            "owner": "parameters",
            "outer": "outer",
            "complete": True,
        }
    ]
    if split:
        p["environments"].append(
            {
                "id": "vars",
                "unit": "u",
                "kind": "function-var",
                "owner": "body",
                "outer": "params",
                "complete": True,
            }
        )
    body_env = "vars" if split else "params"
    p["occurrences"] = p["occurrences"][:1] + [
        {
            "id": "parameter-x",
            "unit": "u",
            "environment": "params",
            "namespace": "value",
            "name": "x",
            "kind": "parameter",
            "start": 5,
            "end": 6,
        },
        {
            "id": "body-x",
            "unit": "u",
            "environment": body_env,
            "namespace": "value",
            "name": "x",
            "kind": "var",
            "start": 100,
            "end": 101,
        },
    ]
    p["references"] = [
        {
            "id": "body-read",
            "unit": "u",
            "region": "body",
            "namespace": "value",
            "name": "x",
            "access": "read",
            "start": 110,
            "end": 111,
        }
    ]
    if closure:
        p["regions"] += [
            region("default", "parameter-default", "parameters", start=30, end=70),
            region(
                "closure", "function-creation", "default", start=40, end=60, split=False
            ),
            region(
                "closure-params",
                "function-parameters",
                "closure",
                "closure-env",
                start=40,
                end=42,
            ),
            region("closure-body", "function-body", "closure", start=42, end=60),
        ]
        p["environments"].append(
            {
                "id": "closure-env",
                "unit": "u",
                "kind": "function-shared",
                "owner": "closure-params",
                "outer": "params",
                "complete": True,
            }
        )
        p["references"].append(
            {
                "id": "closure-read",
                "unit": "u",
                "region": "closure-body",
                "namespace": "value",
                "name": "x",
                "access": "read-write",
                "start": 45,
                "end": 46,
            }
        )
    fill_bindings(p)
    bs = {b["environment"]: b["id"] for b in p["bindings"]}
    p["resolutions"] = [
        {
            "id": "body-read",
            "unit": "u",
            "state": "resolved",
            "origin": body_env,
            "target": bs[body_env],
            "path": [body_env],
        }
    ]
    if closure:
        p["resolutions"].append(
            {
                "id": "closure-read",
                "unit": "u",
                "state": "resolved",
                "origin": "closure-env",
                "target": bs["params"],
                "path": ["closure-env", "params"],
            }
        )
    return p


def test_default_closure_captures_parameter_not_body_binding():
    p = function_payload()
    checked = admit(p).check()
    assert len({r.target for r in checked.resolutions}) == 2
    assert checked.resolutions[1].path == ("closure-env", "params")
    assert checked.value.value == "unknown"  # No copy/alias or value-flow inference.


@pytest.mark.parametrize(
    "simple_shape",
    ["simple", "destructure-without-expression", "rest-without-expression"],
)
def test_no_expression_parameter_and_var_share_binding(simple_shape):
    # These shapes have the same normalized split=false IR; no parser claim.
    e = admit(function_payload(split=False, closure=False))
    b = next(b for b in e.bindings if b.environment == "params")
    assert b.occurrences == ("body-x", "parameter-x")
    assert e.check().resolutions[0].target == b.id


@pytest.mark.parametrize("slot", ["parameter-default", "parameter-computed"])
def test_typed_parameter_expressions_use_parameter_environment(slot):
    p = function_payload()
    p["regions"][4]["slot"] = slot
    assert admit(p).check().resolutions[1].path == ("closure-env", "params")


@pytest.mark.parametrize(
    "mutation",
    [
        "ancestor-scope-target",
        "closure-outer",
        "body-outer",
        "split-rule",
        "default-owner",
        "duplicate-body",
        "missing-params",
    ],
)
def test_function_origin_corruptions_are_rejected(mutation):
    p = function_payload()
    if mutation == "ancestor-scope-target":
        p["resolutions"][0].update(
            origin="params", target=p["resolutions"][1]["target"], path=["params"]
        )
    elif mutation == "closure-outer":
        p["environments"][3]["outer"] = "vars"
    elif mutation == "body-outer":
        p["environments"][2]["outer"] = "outer"
    elif mutation == "split-rule":
        p["regions"][1]["split_parameters"] = False
    elif mutation == "default-owner":
        p["regions"][4]["parent"] = "fn"
    elif mutation == "duplicate-body":
        p["regions"].append({**p["regions"][3], "id": "another-body"})
    elif mutation == "missing-params":
        p["regions"].pop(2)
    with pytest.raises(ValueError):
        admit(p)


def test_coherent_region_rewrite_is_only_ir_consistency_not_source_authentication():
    p = switch_payload()
    old = admit(p)
    # Retype the discriminant as an ordinary evaluation inside the CaseBlock,
    # with identical spans: geometric facts alone cannot authenticate slots.
    p["regions"][2].update(slot="evaluation", parent="cases")
    p["regions"][3].update(start=0)
    p["regions"].append(region("new-disc", "switch-discriminant", "sw", start=2, end=3))
    p["resolutions"][0].update(
        origin="case", target=p["resolutions"][1]["target"], path=["case"]
    )
    new = admit(p)
    assert new.check().evidence.value == "ir-only"
    assert old.digest() != new.digest()
    receipt = core().AdmissionReceipt(
        old.digest(), core().EvidenceStatus.CAPTURE_ATTESTED, "external-test-admission"
    )
    with pytest.raises(ValueError, match="receipt"):
        new.check(receipt)


@pytest.mark.parametrize("status", ["capture-attested", "source-checked"])
def test_external_admission_receipt_has_explicit_caller_trust_boundary(status):
    m = core()
    e = admit(switch_payload())
    receipt = m.AdmissionReceipt(
        e.digest(), m.EvidenceStatus(status), "independently-retained-test-receipt"
    )
    assert e.check(receipt).evidence.value == status
    # An envelope may never supply or upgrade its own evidence.
    p = switch_payload()
    p["receipt"] = asdict(receipt)
    with pytest.raises(ValueError):
        admit(p)


def test_same_payload_hash_and_source_hash_do_not_upgrade_evidence():
    e = admit(switch_payload())
    assert len(e.digest()) == 64
    assert e.check().evidence.value == "ir-only"
    with pytest.raises(ValueError):
        e.check(
            core().AdmissionReceipt(e.digest(), core().EvidenceStatus.IR_ONLY, "self")
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "legacy",
        "future-version",
        "profile",
        "unknown-field",
        "missing-field",
        "unknown-proof",
        "unknown-slot",
        "unknown-state",
        "bool-as-offset",
        "nonbool-complete",
        "duplicate-id",
        "empty-name",
        "namespace",
        "truncated",
        "duplicate-key",
        "source-digest",
        "source-length",
    ],
)
def test_closed_schema_and_source_metadata(mutation):
    p = switch_payload()
    if mutation == "legacy":
        p["version"] = "2"
    elif mutation == "future-version":
        p["version"] = "binding-ir/999"
    elif mutation == "profile":
        p["profile"] = "arbitrary/1"
    elif mutation == "unknown-field":
        p["references"][0]["scope"] = "case"
    elif mutation == "missing-field":
        p["references"][0].pop("region")
    elif mutation == "unknown-proof":
        p["proofs"] = [{"kind": "UNRECOGNIZED_ASSERTION", "status": "proved"}]
    elif mutation == "unknown-slot":
        p["regions"][2]["slot"] = "teleport"
    elif mutation == "unknown-state":
        p["resolutions"][0]["state"] = "proved"
    elif mutation == "bool-as-offset":
        p["references"][0]["start"] = True
    elif mutation == "nonbool-complete":
        p["environments"][0]["complete"] = 1
    elif mutation == "duplicate-id":
        p["references"].append(p["references"][0])
    elif mutation == "empty-name":
        p["references"][0]["name"] = ""
    elif mutation == "namespace":
        p["references"][0]["namespace"] = "type"
    elif mutation == "source-digest":
        p["units"][0]["source_sha256"] = "0" * 64
    elif mutation == "source-length":
        p["units"][0]["byte_length"] += 1
    text = json.dumps(p)
    if mutation == "truncated":
        text = text[:-3]
    if mutation == "duplicate-key":
        text = text.replace('"version":', '"version":"binding-ir/1","version":', 1)
    with pytest.raises(ValueError):
        core().Envelope.from_json(text)


@pytest.mark.parametrize("span", [(0, 2), (-1, 1), (200, 201), (11, 10)])
def test_utf8_boundaries_and_half_open_bounds_are_checked(span):
    import hashlib

    p = switch_payload()
    source = "😀" + "x" * 196
    p["units"][0].update(
        source=source, source_sha256=hashlib.sha256(source.encode()).hexdigest()
    )
    p["occurrences"][0].update(start=4, end=5)
    p["references"][0].update(start=span[0], end=span[1])
    with pytest.raises(ValueError):
        admit(p)


def test_utf8_valid_offsets_and_escaped_decoded_name_are_not_substring_oracles():
    import hashlib

    p = switch_payload()
    source = "😀" + "x" * 196
    p["units"][0].update(
        source=source, source_sha256=hashlib.sha256(source.encode()).hexdigest()
    )
    p["occurrences"][0].update(start=4, end=5)
    # Decoded identifier is an asserted grammar fact; checker does not parse it.
    for d in p["occurrences"]:
        d["name"] = "é"
    for r in p["references"]:
        r["name"] = "é"
    fill_bindings(p)
    bs = {b["environment"]: b["id"] for b in p["bindings"]}
    for r in p["resolutions"]:
        r["target"] = bs[r["origin"]]
    assert admit(p).check().evidence.value == "ir-only"


def test_equal_local_ids_in_different_units_do_not_cross_bind():
    p = switch_payload()
    other = deepcopy(p)
    other["units"][0]["id"] = "other"
    for field in (
        "environments",
        "regions",
        "references",
        "resolutions",
        "occurrences",
    ):
        for record in other[field]:
            record["unit"] = "other"
    fill_bindings(other)
    targets = {b["environment"]: b["id"] for b in other["bindings"]}
    for r in other["resolutions"]:
        r["target"] = targets[r["origin"]]
    for field in (
        "units",
        "environments",
        "regions",
        "references",
        "resolutions",
        "occurrences",
        "bindings",
    ):
        p[field] += other[field]
    assert len(admit(p).check().resolutions) == 4
    p["resolutions"][0]["target"] = other["resolutions"][0]["target"]
    with pytest.raises(ValueError):
        admit(p)


def test_direct_constructor_is_revalidated_before_serialization_or_check():
    e = admit(switch_payload())
    malformed = replace(
        e, references=(replace(e.references[0], start=True), *e.references[1:])
    )
    with pytest.raises(ValueError):
        malformed.to_json()
    with pytest.raises(ValueError):
        malformed.check()


def test_overdeep_region_chain_is_rejected_independently_of_record_order():
    p = switch_payload()
    parent = "root"
    for i in range(257):
        id = "deep-" + str(i)
        p["regions"].append(region(id, "evaluation", parent))
        parent = id
    for order in (p["regions"], list(reversed(p["regions"]))):
        with pytest.raises(ValueError, match="deep"):
            admit({**p, "regions": order})


def test_canonical_grouping_rejects_unknown_kinds_from_direct_constructors():
    m = core()
    d = replace(occurrence("var"), kind="unknown")
    with pytest.raises(ValueError):
        m.canonical_bindings((environment(),), (d,))


def test_duplicate_lexicals_in_lexical_environment_are_rejected():
    m = core()
    with pytest.raises(ValueError, match="coexistence"):
        m.canonical_bindings(
            (environment("block"),), (occurrence("let", "a"), occurrence("let", "b"))
        )


def test_non_boundary_utf8_offset_inside_valid_region_is_rejected():
    import hashlib

    p = switch_payload()
    source = "😀" + "x" * 196
    p["units"][0].update(
        source=source, source_sha256=hashlib.sha256(source.encode()).hexdigest()
    )
    p["occurrences"][0].update(start=1, end=4)
    with pytest.raises(ValueError, match="UTF8"):
        admit(p)
