"""Ownership policy on the normal dispatcher, not snapshot self-consistency."""

from types import SimpleNamespace as N

import pytest

from design_graph.interface.mcp import automatic_source_tool as tool
from design_graph.interface.mcp.tools import ToolDispatcher
from tests.unit.interface.mcp.test_automatic_source_tool import fixture


@pytest.mark.parametrize(
    "origin",
    [
        "unrelated",
        "stale",
        "mixed-community",
        "different-payload",
        "identical-component",
    ],
)
def test_singleton_snapshot_did_not_establish_selected_source_ownership(
    origin, monkeypatch
):
    snapshot = fixture()
    snapshot.community = origin
    selected_body = "function Selected(){return null;}"
    if origin == "identical-component":
        # Even an exact fragment cannot associate the entire document inventory.
        selected_body = snapshot.captures[0].ir.units[0].source
    reader = N(
        _conn=object(),
        get_full_source=lambda name: None,
        model_info=lambda: {"version": 12, "capture": "html_prototype"},
        get_screen_assembly=lambda name: {
            "name": "Selected",
            "skeleton": selected_body,
        },
    )
    monkeypatch.setattr(
        tool, "_snapshot", lambda connection: (snapshot, "unrelated-revision")
    )
    text = ToolDispatcher([("selected", reader)]).dispatch(
        "get_full", {"name": "helper", "aspect": "source"}, "selected"
    )
    assert "Source ownership/correspondence unknown" in text
    assert "function helper() { return PALETTE; }" not in text
    assert "const PALETTE" not in text
    assert "snapshot=unrelated-revision" not in text
    assert "source_selections" in text


def test_real_admitted_foreign_singleton_refused_on_selected_connection(tmp_path):
    """Real native capture + owned Kuzu, not a mocked snapshot admission."""
    import os
    from pathlib import Path

    import kuzu

    from design_graph.capture.binding_capture import BindingCapture
    from design_graph.model.graph.binding_context import (
        BindingRoot,
        BindingSnapshot,
        write_binding_context,
    )
    from design_graph.model.graph.reader import GraphReader
    from design_graph.model.graph.schema import initialize_schema

    keys = ("DG_CAPTURE_NODE", "DG_CAPTURE_ENGINE", "DG_CAPTURE_FINGERPRINT")
    if not all(os.environ.get(key) for key in keys):
        pytest.skip("requires explicitly pinned reviewed native engine")
    producer = BindingCapture(
        node=Path(os.environ[keys[0]]),
        toolchain=Path(os.environ[keys[1]]),
        fingerprint=os.environ[keys[2]],
    )
    body = "function helper(){return 17;}"
    capture = producer.capture(
        body.encode(),
        locator="foreign-document#script/0",
        source_type="script",
        syntax="js",
    )
    unit = capture.ir.units[0]
    roots = tuple(
        BindingRoot(unit.id, r.id)
        for r in capture.ir.regions
        if r.slot.value in ("root", "function-creation")
    )
    snapshot = BindingSnapshot.create("foreign-community", (capture,), roots)
    path = tmp_path / "mixed.db"
    db = kuzu.Database(str(path), buffer_pool_size=128 * 1024 * 1024, max_num_threads=2)
    conn = kuzu.Connection(db)
    try:
        initialize_schema(conn)
        conn.execute("CREATE (:Model {version:12, capture:'html_prototype'})").close()
        conn.execute(
            "CREATE (:Screen {name:'Selected', source_code:'function Selected(){return null;}', source_lang:'js'})"
        ).close()
        conn.execute(
            "CREATE (:Component {name:'Anchor', source_code:$source, source_lang:'js'})",
            {"source": body},
        ).close()
        revision = write_binding_context(conn, snapshot)
    finally:
        conn.close()
        db.close()
    db = kuzu.Database(str(path), buffer_pool_size=128 * 1024 * 1024, max_num_threads=2)
    conn = kuzu.Connection(db)
    try:
        # The exact persisted foreign snapshot passes full production admission.
        admitted, actual = tool._snapshot(conn)
        assert actual == revision and admitted.community == "foreign-community"
        assert tool._records(admitted, "helper", actual)[0]["source"] == body
        dispatcher = ToolDispatcher([("selected", GraphReader(conn))])
        for source in (
            "function Selected(){return null;}",
            body,
            "function Selected(){return 99;}",
        ):
            # Identical fragment and same-shape stale source cannot establish the
            # complete snapshot inventory's selected-document ownership either.
            conn.execute(
                "MATCH (s:Screen {name:'Selected'}) SET s.source_code=$source",
                {"source": source},
            ).close()
            text = dispatcher.dispatch(
                "get_full", {"name": "helper", "aspect": "source"}, "selected"
            )
            assert "Source ownership/correspondence unknown" in text
            assert body not in text
    finally:
        conn.close()
        db.close()
    # Explicit caller-selected evidence remains available, independent of ownership.
    region = next(r for r in capture.ir.regions if r.slot.value == "function-creation")
    text = ToolDispatcher([]).dispatch(
        "get_full",
        {
            "name": "helper",
            "aspect": "source",
            "db": str(path),
            "snapshot": revision,
            "source_selections": [{"unit": unit.id, "region": region.id}],
        },
        "",
    )
    assert body in text
