"""Real new-destination builds, independently sealed ownership and failure controls."""
import json
from pathlib import Path

from tests.unit.pipeline.test_binding_cli import build
from tests.unit.pipeline.test_binding_cli import pytestmark as pytestmark
from tests.unit.pipeline.test_binding_cli_controls import html_source, open_db


def test_normal_fresh_build_owned_after_reopen_and_reusable(tmp_path):
    source = html_source(tmp_path, 'const PALETTE=[17,29]; function helper(){return PALETTE[0];} window.API={hue:helper};')
    # The template is not itself a JS unit. The real producer captures two
    # whole script units, while general capture retains HTML/CSS independently.
    source.write_text(source.read_text().replace('</body>', '<script>const UNSELECTED=71;</script></body>'))
    db = tmp_path / 'owned.db'
    result = build(source, db)
    assert result.returncode == 0, result.stderr
    manifest = json.loads(Path(str(db) + '.binding.json').read_text())
    assert manifest['contract'] == 'binding-build/4'
    assert manifest['ownership']['version'] == 'source-build-ownership/2'
    from design_graph.model.graph.reader import GraphReader
    from design_graph.model.graph.source_build_ownership import (
        load_source_build_ownership,
    )
    database, connection = open_db(db)
    try:
        reader = GraphReader(connection, Path(str(db) + '.state.json'))
        receipt = load_source_build_ownership(reader)
        assert receipt.domain.document == db.stem
        assert len(receipt.general.tables) == 39
        assert receipt.owners
        assert receipt.syntax.captures[0].lexical.engine_fingerprint == manifest['engine']
    finally:
        connection.close()
        database.close()
    reused = build(source, db)
    assert reused.returncode == 0, reused.stderr
    assert json.loads(reused.stdout)['status'] == 'skipped'
