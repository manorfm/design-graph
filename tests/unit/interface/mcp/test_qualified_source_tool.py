"""Qualified source retrieval is explicit evidence, not name/member resolution."""

import hashlib
import os
from pathlib import Path

import kuzu
import pytest

from design_graph.interface.mcp.tools import ToolDispatcher

SOURCE = "const PALETTE = [38, 210]; function helper(name) { return PALETTE[name]; }"


@pytest.fixture(scope="module")
def stored(tmp_path_factory):
    from design_graph.capture.binding_capture import BindingCapture
    from design_graph.model.graph.binding_context import (
        BindingRoot, BindingSnapshot, write_binding_context,
    )

    provider = BindingCapture(
        node=Path(os.environ["DG_CAPTURE_NODE"]),
        toolchain=Path(os.environ["DG_CAPTURE_ENGINE"]),
        fingerprint=os.environ["DG_CAPTURE_FINGERPRINT"],
    )
    capture = provider.capture(SOURCE.encode(), locator="fixture.js", source_type="module", syntax="js")
    unit = capture.ir.units[0]
    function = next(r for r in capture.ir.regions if r.slot.value == "function-creation")
    snapshot = BindingSnapshot.create("source-test", (capture,), (BindingRoot(unit.id, function.id),))
    path = tmp_path_factory.mktemp("qualified-source") / "source.db"
    database = kuzu.Database(str(path), buffer_pool_size=128 * 1024 * 1024, max_num_threads=2)
    connection = kuzu.Connection(database)
    try:
        revision = write_binding_context(connection, snapshot)
    finally:
        connection.close()
        database.close()
    return {"db": str(path), "snapshot": revision}, unit, function


def selected(stored, palette=False):
    args, unit, function = stored
    interval = [0, SOURCE.index(" function")]
    if not palette:
        interval = [function.start, function.end]
    body = SOURCE.encode()[slice(*interval)]
    selection = {
        "unit": unit.id, "region": unit.root_region if palette else function.id,
        "mode": "retained-interval" if palette else "region",
        "interval": interval,
        "receipt": {"unit_sha256": unit.source_sha256, "interval": interval,
                    "source_sha256": hashlib.sha256(body).hexdigest()},
    }
    return {**args, "name": "helper", "aspect": "source", "source_selections": [selection]}


def test_normal_get_full_returns_explicit_helper_source(stored):
    result = ToolDispatcher([]).dispatch("get_full", selected(stored), "")
    assert SOURCE[SOURCE.index("function"):] in result
    assert "initialization/value unknown" in result


def test_normal_get_full_returns_explicit_initializer_syntax(stored):
    result = ToolDispatcher([]).dispatch("get_full", selected(stored, True), "")
    assert "const PALETTE = [38, 210];" in result
    assert "syntax only" in result


class LegacyReader:
    def get_screen_assembly(self, name):
        return {"name": "Home", "skeleton": "function Home() {}", "source_lang": "js",
                "relations": {}, "components": [], "data": [], "unread_lists": [],
                "tokens": [], "resources": [], "actions": [], "states": []}


def test_default_dispatch_did_not_certify_unknown_dependency_closure():
    result = ToolDispatcher([("doc", LegacyReader())]).dispatch("assemble_page", {"name": "Home"}, "")
    assert "Tudo o que a tela usa está acima — nada foi cortado." not in result
    assert "Source closure incomplete/unknown" in result


@pytest.mark.parametrize("change", [
    {"snapshot": "0" * 64}, {"expected_sha256": "0" * 64}, {"part": 999},
    {"part": True}, {"part": 1.5}, {"part": 0}, {"source_selections": []},
    {"source_selections": [{}]}, {"source_selections": [None]},
    {"db": "relative.db"}, {"doc": "another-doc"}, {"snapshot": None},
])
def test_public_rejected_invalid_or_mixed_qualifiers(stored, change):
    args = selected(stored)
    args.update(change)
    with pytest.raises(ValueError):
        ToolDispatcher([]).dispatch("get_full", args, "")


@pytest.mark.parametrize("field,value", [
    ("unit", "missing"), ("region", "missing"), ("interval", [True, 3]),
    ("interval", [0, 3]), ("receipt", {"path": "/etc/passwd"}),
])
def test_public_selection_did_not_fallback_to_name(stored, field, value):
    args = selected(stored)
    args["source_selections"][0][field] = value
    with pytest.raises(ValueError):
        ToolDispatcher([]).dispatch("get_full", args, "")


def test_public_receipt_mismatch_rejected_even_with_admitted_snapshot(stored):
    args = selected(stored)
    args["source_selections"][0]["receipt"]["source_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="receipt"):
        ToolDispatcher([]).dispatch("get_full", args, "")


def test_duplicate_selections_rejected(stored):
    args = selected(stored)
    args["source_selections"] *= 2
    with pytest.raises(ValueError, match="duplicate"):
        ToolDispatcher([]).dispatch("get_full", args, "")


def test_selection_and_source_budgets(stored, monkeypatch):
    from design_graph.interface.mcp import qualified_source_tool as tool

    args = selected(stored)
    args["source_selections"] *= tool.MAX_SELECTIONS + 1
    with pytest.raises(ValueError, match="budget"):
        ToolDispatcher([]).dispatch("get_full", args, "")
    monkeypatch.setattr(tool, "MAX_SOURCE_BYTES", 2)
    with pytest.raises(ValueError, match="budget"):
        ToolDispatcher([]).dispatch("get_full", selected(stored), "")


def test_wrong_database_failed_without_reader_fallback(stored, tmp_path):
    path = tmp_path / "empty.db"
    database = kuzu.Database(str(path), buffer_pool_size=128 * 1024 * 1024, max_num_threads=2)
    database.close()
    args = {**selected(stored), "db": str(path)}
    with pytest.raises(ValueError, match="no admitted"):
        ToolDispatcher([("doc", LegacyReader())]).dispatch("get_full", args, "doc")


def test_repeat_reads_preserved_db_and_unselected_legacy_reader(stored):
    path = Path(stored[0]["db"])
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    dispatcher = ToolDispatcher([("doc", LegacyReader())])
    args = selected(stored)
    result = dispatcher.dispatch("get_full", args, "doc")
    assert dispatcher.dispatch("get_full", args, "doc") == result
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert "Home" in dispatcher.dispatch("assemble_page", {"name": "Home"}, "doc")


def _provider():
    from design_graph.capture.binding_capture import BindingCapture

    return BindingCapture(
        node=Path(os.environ["DG_CAPTURE_NODE"]),
        toolchain=Path(os.environ["DG_CAPTURE_ENGINE"]),
        fingerprint=os.environ["DG_CAPTURE_FINGERPRINT"],
    )


def test_coherent_source_ir_rewrite_rejected_by_original_receipt_at_public_boundary(stored, tmp_path):
    from design_graph.model.graph.binding_context import BindingRoot, BindingSnapshot, write_binding_context

    changed = _provider().capture(SOURCE.replace("38", "39").encode(), locator="fixture.js", source_type="module", syntax="js")
    unit = changed.ir.units[0]
    region = next(r for r in changed.ir.regions if r.slot.value == "function-creation")
    snapshot = BindingSnapshot.create("coherent-rewrite", (changed,), (BindingRoot(unit.id, region.id),))
    path = tmp_path / "rewritten.db"
    database = kuzu.Database(str(path), buffer_pool_size=128 * 1024 * 1024, max_num_threads=2)
    connection = kuzu.Connection(database)
    try:
        revision = write_binding_context(connection, snapshot)
    finally:
        connection.close()
        database.close()
    args = selected(stored)
    args.update(db=str(path), snapshot=revision)
    args["source_selections"][0].update(unit=unit.id, region=region.id)
    with pytest.raises(ValueError, match="retained receipt mismatch"):
        ToolDispatcher([]).dispatch("get_full", args, "")


def test_unrelated_binding_change_preserved_selected_source(stored):
    from design_graph.interface.mcp.qualified_source_tool import _records
    from design_graph.model.graph.binding_context import BindingSnapshot, read_binding_context

    database = kuzu.Database(stored[0]["db"], read_only=True, buffer_pool_size=128 * 1024 * 1024, max_num_threads=2)
    connection = kuzu.Connection(database)
    try:
        original = read_binding_context(connection, stored[0]["snapshot"])
    finally:
        connection.close()
        database.close()
    provider = _provider()
    results = []
    for name in ("UNRELATED", "OTHERNAME"):
        extra = provider.capture(f"const {name}=1;".encode(), locator="unrelated.js", source_type="module", syntax="js")
        snapshot = BindingSnapshot.create(original.community, (*original.captures, extra), original.roots)
        results.append(_records(snapshot, stored[0]["snapshot"], selected(stored)["source_selections"]))
    assert results[0] == results[1]


def test_source_supplement_pagination_kept_every_byte_and_counted_parts():
    import re

    from design_graph.interface.mcp.qualified_source_tool import _render

    source = "const item = 1;\n" * 4000
    record = {"snapshot": "s", "unit": "u", "region": "r", "interval": [0, len(source)],
              "unit_sha256": "u", "source_sha256": "b", "source": source,
              "syntax": "js", "selection": "exact region", "fidelity": "formatting control"}
    first = _render("get_full", {}, [record], None)
    total = int(re.search(r"parte 1/(\d+)", first).group(1))
    assert total >= 3
    pages = [_render("get_full", {"part": n}, [record], None) for n in range(1, total + 1)]
    chunks = [re.search(r"```js\n(.*?)\n```", page, re.S).group(1) for page in pages]
    assert "\n".join(chunks) == source
    assert _render("get_full", {"part": total}, [record], None) == pages[-1]
    with pytest.raises(ValueError, match="part"):
        _render("get_full", {"part": total + 1}, [record], None)


def test_honesty_correction_preserved_source_literals():
    from design_graph.interface.mcp.qualified_source_tool import FALSE_COMPLETENESS, honest_coverage

    code = f'```jsx\nconst label = "{FALSE_COMPLETENESS}";\n```'
    output = honest_coverage(code + "\n## 8. Completude\n" + FALSE_COMPLETENESS)
    assert code in output
    assert output.endswith("not certified.")


def test_wrong_region_did_not_reinterpret_body_as_root_interval(stored):
    args = selected(stored)
    args["source_selections"][0]["region"] = stored[1].root_region
    with pytest.raises(ValueError, match="region"):
        ToolDispatcher([]).dispatch("get_full", args, "")
