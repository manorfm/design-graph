"""Real bounded Kuzu persistence, separate from legacy graph ownership."""

import os
from contextlib import contextmanager
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import kuzu
import pytest


@contextmanager
def connection(path):
    db = kuzu.Database(str(path), buffer_pool_size=128 * 1024 * 1024, max_num_threads=2)
    try:
        con = kuzu.Connection(db)
        try:
            yield con
        finally:
            con.close()
    finally:
        db.close()


def test_cli_qualified_route():
    from design_graph.interface.cli.query import parse_query_args

    args = parse_query_args(
        [
            "source-candidate",
            "--db",
            "/nonexistent/owned",
            "--snapshot",
            "a" * 64,
            "--input-artifact",
            "fixture:input",
            "--inventory-unit",
            "unit:one",
            "--unit",
            "unit:one",
            "--use",
            "u1",
        ]
    )
    assert args.command == "source-candidate"
    assert args.inventory_units == ("unit:one",)


def snapshot():
    from design_graph.model.graph.source_syntax_context import SourceSyntaxSnapshot
    from design_graph.model.source_syntax import SourceInventory

    caps = captures()
    return SourceSyntaxSnapshot.create(
        SourceInventory(
            "b" * 64, "fixture:input", tuple(c.source_syntax.unit for c in caps)
        ),
        caps,
    )


def test_collision_rollback_and_next_call_mutation(tmp_path):
    from design_graph.model.graph import source_syntax_context as s
    from design_graph.model.graph.binding_context import _rows

    value = snapshot()
    with connection(tmp_path / "collision") as con:
        key = s.write_source_syntax(con, value)
        for candidate in (
            value,
            replace(value, scope=replace(value.scope, input_artifact="other")),
        ):
            with pytest.raises(RuntimeError):
                s.write_source_syntax(con, candidate)
            assert s.read_source_syntax(con, key) == value
        _rows(
            con,
            "MATCH (s:BindingContextSnapshot) WHERE s.snapshot_id=$id SET s.payload=$payload",
            {
                "id": key,
                "payload": value.to_json().replace(
                    "source-syntax-context/1", "source-syntax-context/9"
                ),
            },
        )
        with pytest.raises(ValueError):
            s.read_source_syntax(con, key)
        _rows(
            con,
            "MATCH (s:BindingContextSnapshot) WHERE s.snapshot_id=$id SET s.payload=$payload",
            {"id": key, "payload": value.to_json()},
        )
        assert s.read_source_syntax(con, key) == value


def test_failure_atomic_schema_rollback(tmp_path, monkeypatch):
    from design_graph.model.graph import binding_context as physical
    from design_graph.model.graph import source_syntax_context as s

    with connection(tmp_path / "atomic") as con:

        def fail(_):
            raise ValueError("injected failure after transactional DDL")

        with monkeypatch.context() as patch:
            patch.setattr(physical, "_check_schema", fail)
            with pytest.raises(ValueError, match="injected"):
                s.write_source_syntax(con, snapshot())
        assert not physical._has_extension(con)
        s.write_source_syntax(con, snapshot())


def test_legacy_and_exact_qualification(tmp_path):
    from design_graph.model.graph import binding_context as old
    from design_graph.model.graph import source_syntax_context as s

    value = snapshot()
    with connection(tmp_path / "legacy") as con:
        assert s.read_source_syntax(con, value.scope.snapshot) is None
        legacy = old.BindingSnapshot.create(
            "legacy",
            tuple(c.lexical for c in value.captures),
            tuple(
                old.BindingRoot(c.source_syntax.unit, c.lexical.ir.regions[0].id)
                for c in value.captures
            ),
        )
        key = old.write_binding_context(con, legacy)
        assert old.read_binding_context(con, key) == legacy
        with pytest.raises(ValueError):
            s.read_source_syntax(con, key)
        s.write_source_syntax(con, value)
        assert old.read_binding_context(con, key) == legacy
        for artifact, units in [
            ("wrong", value.scope.units),
            (value.scope.input_artifact, value.scope.units[:1]),
            (value.scope.input_artifact, value.scope.units[::-1]),
        ]:
            with pytest.raises(ValueError):
                s.read_project_source_syntax(
                    con,
                    value.scope.snapshot,
                    input_artifact=artifact,
                    units=units,
                    unit=value.scope.units[1],
                    use="u1",
                )
        with pytest.raises(ValueError):
            old.read_binding_context(con, value.scope.snapshot)


@pytest.mark.parametrize(
    "mutation",
    [
        "version",
        "hash",
        "producer",
        "scope",
        "duplicate",
        "bool",
        "enum",
        "span",
        "mixed",
        "checked",
        "duplicate-json",
    ],
)
def test_hostile_closed_transport(mutation):
    import json

    from design_graph.model.graph import source_syntax_context as s

    value = snapshot()
    data = json.loads(value.to_json())
    body = data["snapshot"]
    if mutation == "version":
        body["version"] = "binding-context/2"
    if mutation == "hash":
        body["inventory"][0]["source_sha256"] = "0" * 64
    if mutation == "producer":
        body["inventory"][0]["producer_fingerprint"] = "0" * 64
    if mutation == "scope":
        body["scope"]["units"].reverse()
    if mutation == "duplicate":
        body["captures"].append(body["captures"][0])
    if mutation == "bool":
        body["captures"][0]["source_syntax"]["publications"][0]["members"][0][
            "computed"
        ] = 0
    if mutation == "enum":
        body["captures"][0]["lexical"]["ir"]["occurrences"][0]["kind"] = "unrecognized"
    if mutation == "span":
        body["captures"][1]["source_syntax"]["uses"][0]["member_span"]["start"] = True
    if mutation == "mixed":
        body["captures"][0]["source_syntax"]["unit"] = body["captures"][1][
            "source_syntax"
        ]["unit"]
    if mutation == "checked":
        body["checked"] = True
    text = json.dumps(data)
    if mutation == "duplicate-json":
        text = text.replace('"sha256":', '"sha256":"' + "0" * 64 + '","sha256":', 1)
    with pytest.raises(ValueError):
        s.SourceSyntaxSnapshot.from_json(text)


def test_noncanonical_unit_locator_rejected():
    from design_graph.model.graph import source_syntax_context as s

    value = snapshot()
    first = value.captures[0]
    ir = first.lexical.ir
    relabeled = replace(
        first,
        lexical=replace(
            first.lexical,
            ir=replace(ir, units=(replace(ir.units[0], locator="forged:locator"),)),
        ),
    )
    with pytest.raises(ValueError, match="canonical"):
        s.SourceSyntaxSnapshot.create(value.scope, (relabeled, value.captures[1]))


def test_create_preflights_inventory_before_iteration():
    from design_graph.model.graph import source_syntax_context as s
    value = snapshot()
    with pytest.raises(ValueError, match='immutable'):
        s.SourceSyntaxSnapshot.create(value.scope, iter(value.captures))


def test_direct_objects_and_caps(monkeypatch):
    from design_graph.model.graph import source_syntax_context as s

    value = snapshot()
    for invalid in (
        replace(value, version=True),
        replace(value, inventory=value.inventory * 2),
        replace(value, captures=value.captures * 2),
        replace(value, scope=replace(value.scope, units=(True,))),
    ):
        with pytest.raises(ValueError):
            invalid.to_json()
    for text in ("[" * 66 + "]" * 66, '{"sha256":NaN,"snapshot":{}}'):
        with pytest.raises(ValueError):
            s.SourceSyntaxSnapshot.from_json(text)
    monkeypatch.setattr(s, "MAX_UNITS", 1)
    with pytest.raises(ValueError, match="budget"):
        value.to_json()


def test_prefetch_caps_and_physical_version(tmp_path, monkeypatch):
    from design_graph.model.graph import source_syntax_context as s
    from design_graph.model.graph.binding_context import _rows

    value = snapshot()
    with connection(tmp_path / "caps") as con:
        s.write_source_syntax(con, value)
        with monkeypatch.context() as patch:
            patch.setattr(s, "MAX_JSON_CHARS", 1)
            with pytest.raises(ValueError, match="pre-fetch"):
                s.read_source_syntax(con, value.scope.snapshot)
        _rows(
            con,
            "MATCH (s:BindingContextSnapshot) SET s.format=$format",
            {"format": "wrong"},
        )
        with pytest.raises(ValueError, match="physical"):
            s.read_source_syntax(con, value.scope.snapshot)


def test_coherent_rewrite_needs_external_anchor(tmp_path):
    from design_graph.model.graph import source_syntax_context as s
    from design_graph.model.graph.binding_context import _rows

    value = snapshot()
    newer = replace(value, scope=replace(value.scope, input_artifact="coherent:other"))
    with connection(tmp_path / "rewrite") as con:
        s.write_source_syntax(con, value)
        _rows(
            con,
            "MATCH (s:BindingContextSnapshot) SET s.payload=$payload",
            {"payload": newer.to_json()},
        )
        assert s.read_source_syntax(con, value.scope.snapshot) == newer
        with pytest.raises(ValueError, match="custody"):
            s.read_source_syntax(
                con, value.scope.snapshot, expected_sha256=value.digest()
            )
        assert (
            s.read_source_syntax(
                con, value.scope.snapshot, expected_sha256=newer.digest()
            )
            == newer
        )
        wrong = replace(newer, scope=replace(newer.scope, snapshot="c" * 64))
        _rows(
            con,
            "MATCH (s:BindingContextSnapshot) SET s.payload=$payload",
            {"payload": wrong.to_json()},
        )
        with pytest.raises(ValueError, match="identity"):
            s.read_source_syntax(con, value.scope.snapshot)


@lru_cache(maxsize=1)
def captures():
    from design_graph.capture.binding_capture import BindingCapture

    producer = BindingCapture(
        node=Path(os.environ["DG_CAPTURE_NODE"]),
        toolchain=Path(os.environ["DG_CAPTURE_ENGINE"]),
        fingerprint=os.environ["DG_CAPTURE_FINGERPRINT"],
    )
    return tuple(
        producer.capture_source_syntax(
            source, locator=locator, source_type="script", syntax="js"
        )
        for source, locator in (
            (b"function real(){} window.V6K={hueFromName:real};", "test:provider"),
            (b"const K=window.V6K; K.hueFromName();", "test:consumer"),
        )
    )


def test_typed_append_cold_qualified_roundtrip(tmp_path):
    import importlib.util

    from design_graph.model.graph import binding_context

    assert importlib.util.find_spec("design_graph.model.graph.source_syntax_context"), (
        "missing versioned source syntax persistence"
    )
    from design_graph.model.graph import source_syntax_context as storage
    from design_graph.model.source_syntax import SourceInventory

    caps = captures()
    scope = SourceInventory(
        "a" * 64, "test:input", tuple(c.source_syntax.unit for c in caps)
    )
    snapshot = storage.SourceSyntaxSnapshot.create(scope, caps)
    path = tmp_path / "owned.kuzu"
    db = kuzu.Database(str(path), buffer_pool_size=128 * 1024 * 1024, max_num_threads=2)
    try:
        con = kuzu.Connection(db)
        try:
            revision = storage.write_source_syntax(con, snapshot)
            assert revision == scope.snapshot
            assert (
                len(
                    binding_context._rows(
                        con, "CALL table_info('BindingContextSnapshot') RETURN *"
                    )
                )
                == 3
            )
        finally:
            con.close()
    finally:
        db.close()
    db = kuzu.Database(
        str(path), read_only=True, buffer_pool_size=128 * 1024 * 1024, max_num_threads=2
    )
    try:
        con = kuzu.Connection(db)
        try:
            restored = storage.read_source_syntax(
                con, revision, expected_sha256=snapshot.digest()
            )
            assert restored == snapshot
            result = storage.read_project_source_syntax(
                con,
                revision,
                input_artifact=scope.input_artifact,
                units=scope.units,
                unit=scope.units[1],
                use="u1",
                expected_sha256=snapshot.digest(),
            )
            assert result.selection.status == "source-candidate"
            assert result.selection.runtime_claim is False
            assert result.selection.candidates[0].occurrences == ("d0",)
            assert result.inventory == snapshot.inventory
            assert result.source_payload_ownership == "unknown"
        finally:
            con.close()
    finally:
        db.close()
