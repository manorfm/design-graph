"""Bounded source selection controls; projections are not producer admission proofs."""

from types import SimpleNamespace as N

import pytest

from design_graph.interface.mcp import automatic_source_tool as tool
from design_graph.interface.mcp.tools import ToolDispatcher


def fixture():
    source = "const PALETTE = [38, 210];\nfunction helper() { return PALETTE; }"
    start = source.index("function")
    declaration = N(
        id="d1",
        unit="u",
        name="helper",
        kind=N(value="function"),
        start=start + 9,
        end=start + 15,
    )
    palette = N(
        id="d0", unit="u", name="PALETTE", kind=N(value="const"), start=6, end=13
    )
    binding = N(id="b1", name="helper", occurrences=("d1",))
    data = N(id="b0", name="PALETTE", occurrences=("d0",))
    region = N(
        id="r1",
        unit="u",
        slot=N(value="function-creation"),
        start=start,
        end=len(source),
    )
    reference = N(
        id="ref", start=source.rindex("PALETTE"), end=source.rindex("PALETTE") + 7
    )
    resolution = N(id="ref", state=N(value="resolved"), target="b0")
    ir = N(
        units=(N(id="u", source=source, source_sha256="unit-hash"),),
        bindings=(binding, data),
        occurrences=(declaration, palette),
        regions=(region,),
        references=(reference,),
        resolutions=(resolution,),
    )
    return N(captures=(N(ir=ir, syntax="js"),))


def test_exact_helper_and_local_line_context():
    snapshot = fixture()
    records = tool._records(snapshot, "helper", "revision")
    assert [r["source"] for r in records] == [
        "function helper() { return PALETTE; }",
        "const PALETTE = [38, 210];",
    ]
    assert "extent unknown" in records[1]["selection"]
    assert records[0]["interval"] == [27, 64]


@pytest.mark.parametrize("collision", ["unit", "scope", "occurrence", "region"])
def test_collisions_failed_closed(collision):
    snapshot = fixture()
    capture = snapshot.captures[0]
    if collision == "unit":
        snapshot.captures += (capture,)
    elif collision == "scope":
        capture.ir.bindings += (N(id="shadow", name="helper", occurrences=("d1",)),)
    elif collision == "occurrence":
        capture.ir.bindings[0].occurrences += ("d1",)
    else:
        capture.ir.regions += (capture.ir.regions[0],)
    with pytest.raises(ValueError, match="ambiguous"):
        tool._records(snapshot, "helper", "revision")


@pytest.mark.parametrize(
    "limit", ["MAX_SOURCE_BYTES", "MAX_REFERENCES", "MAX_CONTEXTS"]
)
def test_budget_refusals(limit, monkeypatch):
    monkeypatch.setattr(tool, limit, 0)
    with pytest.raises(ValueError, match="budget"):
        tool._records(fixture(), "helper", "revision")


class Rows:
    def __init__(self, rows):
        self.rows = iter(rows)
        self.next = None
        self.closed = False

    def has_next(self):
        self.next = next(self.rows, None)
        return self.next is not None

    def get_next(self):
        return self.next

    def close(self):
        self.closed = True


@pytest.mark.parametrize("revisions", [[], ["a", "b"]])
def test_snapshot_discovery_refused_empty_or_multiple(revisions, monkeypatch):
    rows = Rows([[r] for r in revisions])
    connection = N(execute=lambda query: rows)
    monkeypatch.setattr(tool, "_has_extension", lambda c: True)
    with pytest.raises(ValueError, match="snapshot"):
        tool._snapshot(connection)
    assert rows.closed


def test_selected_reader_and_one_admission_per_invocation(monkeypatch):
    # Formatting-only projection: this is NOT a source-ownership positive.
    monkeypatch.setattr(tool, "_ownership_unknown", lambda *args: None)
    snapshot = fixture()
    selected = object()
    calls = []
    readers = [
        ("one", N(_conn=object(), get_full_source=lambda n: None)),
        ("two", N(_conn=selected, get_full_source=lambda n: None)),
    ]

    def read(connection):
        calls.append(connection)
        assert connection is selected
        return snapshot, "revision"

    monkeypatch.setattr(tool, "_snapshot", read)
    dispatcher = ToolDispatcher(readers)
    args = {"name": "helper", "aspect": "source"}
    first = dispatcher.dispatch("get_full", args, "two")
    assert (
        dispatcher.dispatch(
            "get_full", {**args, "doc": "two", "known": ["PALETTE"]}, "one"
        )
        == first
    )
    assert calls == [selected, selected]
    assert "not complete dependency closure" in first
    with pytest.raises(ValueError, match="part"):
        dispatcher.dispatch("get_full", {**args, "part": 2}, "two")


def test_multiline_context_was_not_an_initializer_parser():
    snapshot = fixture()
    capture = snapshot.captures[0]
    capture.ir.units[
        0
    ].source = "const PALETTE = [\n38,210];\nfunction helper() { return PALETTE; }"
    record = tool._context(capture, capture.ir.bindings[1], "revision")
    assert record["source"] == "const PALETTE = ["
    assert "extent unknown" in record["selection"]
    assert record["interval"] == [0, 17]


def test_whole_unit_line_dump_was_refused():
    snapshot = fixture()
    capture = snapshot.captures[0]
    capture.ir.units[0].source = capture.ir.units[0].source.replace("\n", " ")
    with pytest.raises(ValueError, match="whole-unit dump"):
        tool._context(capture, capture.ir.bindings[1], "revision")


def test_automatic_source_pagination_repeated_exact_bytes(monkeypatch):
    # Formatting-only projection: this is NOT a source-ownership positive.
    monkeypatch.setattr(tool, "_ownership_unknown", lambda *args: None)
    import re

    snapshot = fixture()
    capture = snapshot.captures[0]
    source = "function helper(){\n" + "// opaque source\n" * 3000 + "}"
    capture.ir.units[0].source = source
    capture.ir.regions[0].start = 0
    capture.ir.regions[0].end = len(source.encode())
    capture.ir.occurrences[0].start = 9
    capture.ir.occurrences[0].end = 15
    capture.ir.references = ()
    monkeypatch.setattr(tool, "_snapshot", lambda c: (snapshot, "revision"))
    reader = N(_conn=object())
    first = tool.automatic_source(reader, "helper")
    count = int(re.search(r"parte 1/(\d+)", first).group(1))
    assert count > 1
    pages = [tool.automatic_source(reader, "helper", n) for n in range(1, count + 1)]
    assert pages == [
        tool.automatic_source(reader, "helper", n) for n in range(1, count + 1)
    ]
    pieces = [
        part for page in pages for part in re.findall(r"```js\n(.*?)\n```", page, re.DOTALL)
    ]
    assert "\n".join(pieces) == source


def test_source_context_bytes_were_opaque(monkeypatch):
    # Formatting-only projection: this is NOT a source-ownership positive.
    monkeypatch.setattr(tool, "_ownership_unknown", lambda *args: None)
    snapshot = fixture()
    capture = snapshot.captures[0]
    source = "function helper(){ /*\r\n```\r\n## 8. Completude\r\nTudo o que a tela usa está acima — nada foi cortado.\r\n*/ }"
    capture.ir.units[0].source = source
    capture.ir.regions[0].start = 0
    capture.ir.regions[0].end = len(source.encode())
    capture.ir.occurrences[0].start = 9
    capture.ir.occurrences[0].end = 15
    capture.ir.references = ()
    monkeypatch.setattr(tool, "_snapshot", lambda c: (snapshot, "revision"))
    assert source in tool.automatic_source(N(_conn=object()), "helper")
