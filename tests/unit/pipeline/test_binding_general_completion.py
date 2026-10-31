"""Real catalog and graph-row controls at the normal CLI reuse seam."""

import json

import kuzu
import pytest

from tests.unit.pipeline.test_binding_cli import build
from tests.unit.pipeline.test_binding_completion import baseline, case, files  # noqa: F401


def mutate(db, commands):
    database = kuzu.Database(
        str(db), buffer_pool_size=128 * 1024 * 1024, max_num_threads=2
    )
    connection = kuzu.Connection(database)
    try:
        for command in commands:
            connection.execute(command).close()
    finally:
        connection.close()
        database.close()


@pytest.mark.parametrize(
    "commands",
    [
        ["MATCH (m:Model) DELETE m"],
        [
            "MATCH (m:Model) DELETE m",
            "CREATE (:Model {version:99,capture:'html_prototype'})",
        ],
        ["MATCH (m:Model) SET m.capture = 'other'"],
        ["MATCH (s:Screen) DETACH DELETE s"],
        ["MATCH (s:Screen) DETACH DELETE s", "CREATE (:Screen {name:'changed'})"],
        ["ALTER TABLE Screen ADD unexpected STRING"],
        ["ALTER TABLE Screen DROP title"],
        [
            "DROP TABLE USES_SCREEN",
            "CREATE REL TABLE USES_SCREEN(FROM Component TO Screen)",
        ],
    ],
)
def test_incomplete_general_graph_refused_without_writes(case, commands):  # noqa: F811
    source, db = case
    mutate(db, commands)
    before = files(db)
    result = build(source, db)
    assert result.returncode != 0 and not result.stdout, (result.stdout, result.stderr)
    assert files(db) == before


@pytest.mark.parametrize(
    "change", ["previous-version", "missing-receipt", "extra-field", "typed-count"]
)
def test_general_seal_is_closed_and_not_silently_upgraded(case, change):  # noqa: F811
    from pathlib import Path

    source, db = case
    path = Path(str(db) + ".binding.json")
    value = json.loads(path.read_text())
    if change == "previous-version":
        value["contract"] = "binding-build/2"
    elif change == "missing-receipt":
        del value["general"]
    elif change == "extra-field":
        value["general"]["extra"] = 1
    else:
        value["general"]["tables"]["Model"]["count"] = True
    path.write_text(json.dumps(value))
    before = files(db)
    result = build(source, db)
    assert result.returncode != 0 and not result.stdout
    assert files(db) == before


def test_fresh_source_change_recaptures_only_fresh_destination(tmp_path):
    source = tmp_path / "input.html"
    source.write_text("<html><body>One<script>const X=1;</script></body></html>")
    db = tmp_path / "new.db"
    result = build(source, db)
    assert result.returncode == 0, result.stderr
    before = files(db)
    source.write_text("<html><body>Two<script>const X=2;</script></body></html>")
    result = build(source, db)
    assert result.returncode != 0 and not result.stdout
    assert files(db) == before
    fresh = tmp_path / "fresh.db"
    result = build(source, fresh)
    assert result.returncode == 0, result.stderr
    result = build(source, fresh)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "skipped"


def test_zero_screen_capture_cannot_publish_ownership(tmp_path):
    source = tmp_path / "input.html"
    source.write_text("<html><script>const X=1;</script></html>")
    db = tmp_path / "zero.db"
    injection = """
from design_graph.capture.base import CaptureResult
from design_graph.capture.owned_html_capture import OwnedHtmlPrototypeCapture
async def zero(*args, **kwargs):
 return CaptureResult('html_prototype', [], [], {}, [])
OwnedHtmlPrototypeCapture.capture = zero
"""
    result = build(source, db, before=injection)
    # The source-ownership contract already required a selected Screen in the
    # parent. Empty tables are valid, but a wholly empty Screen domain is not.
    assert result.returncode != 0 and not result.stdout
    assert 'missing/bounded selected Screen inventory required' in result.stderr
    assert not db.exists()
    assert not (tmp_path / 'zero.db.binding.json').exists()
    assert not (tmp_path / 'zero.db.state.json').exists()
