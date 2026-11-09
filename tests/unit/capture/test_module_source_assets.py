"""Explicit module files preserve helpers without claiming dependency linkage."""
import hashlib

import kuzu
import pytest

from design_graph.capture.resources import script_resource
from design_graph.interface.mcp.asset_tool import get_asset
from design_graph.model.graph.reader import GraphReader
from design_graph.model.graph.schema import initialize_schema
from design_graph.model.graph.writer import GraphWriter

SOURCE = '/* kit.jsx v1 */\n(() => { const R = {lg: 8}; function close() { return "ação"; } window.K = {R, close}; })();\n'.encode()


def test_own_module_keeps_exact_bytes_and_bundle_locator():
    resource = script_resource('kit-entry', SOURCE)
    assert [(a.mime, a.content) for a in resource.files] == [('text/javascript', SOURCE)]
    assert 'kit-entry' in resource.detail
    assert resource.sha256 == hashlib.sha256(SOURCE).hexdigest()


@pytest.mark.parametrize('content', [
    b'/**\n * @license React\n * react.development.js\n */\nvar ReactVersion = "18.3.1";',
    b'!function(e,t){t((e=self).Babel={})}(this,function(e){e.transformScriptTags=V,e.version="7.29.0"})',
    b'// GENERATED from dc-runtime/src/*.ts - do not edit.\n"use strict";(()=>{})();',
])
def test_recognized_infrastructure_remains_description_only(content):
    assert script_resource('infra', content).files == ()


def test_module_roundtrip_closed_writer_readonly_get_asset(tmp_path):
    path = tmp_path / 'module.db'
    db = kuzu.Database(str(path), buffer_pool_size=128 * 1024 * 1024, max_num_threads=2)
    conn = kuzu.Connection(db)
    initialize_schema(conn)
    resource = script_resource('kit-entry', SOURCE)
    writer = GraphWriter(conn)
    writer.write_resources([resource])
    writer.commit()
    conn.close()
    db.close()
    db = kuzu.Database(str(path), read_only=True, buffer_pool_size=128 * 1024 * 1024, max_num_threads=2)
    conn = kuzu.Connection(db)
    try:
        output = get_asset(GraphReader(conn), resource.name, tmp_path)
        files = list((tmp_path / 'design-graph-assets').rglob('*.js'))
        assert len(files) == 1, output
        assert files[0].read_bytes() == SOURCE
        assert resource.files[0].sha256[:16] in output
    finally:
        conn.close()
        db.close()
