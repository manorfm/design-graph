"""
Integration test: an inline SVG icon reused across components is stored once
in the graph and expanded back to its full markup when a component is read.

Exercises the full round trip: extraction (icon_extractor) → graph write
(GraphWriter.write_icons) → graph read (GraphReader._resolve_icons).
"""

from __future__ import annotations

import asyncio

import kuzu
import pytest

from design_graph.graph.reader import GraphReader
from design_graph.pipeline.coordinator import run_pipeline

ICON_SVG = '<svg viewBox="0 0 24 24"><path d="M12 2L2 7 12 12 22 7z"/></svg>'

HTML = f"""
<!DOCTYPE html>
<html>
<body>
<script>
function IconButtonA() {{
  return (
    <button>
      {ICON_SVG}
      Confirm
    </button>
  );
}}

function IconButtonB() {{
  return (
    <button>
      {ICON_SVG}
      Cancel
    </button>
  );
}}
</script>
</body>
</html>
"""


@pytest.fixture(scope="module")
def icon_graph(tmp_path_factory):
    tmp        = tmp_path_factory.mktemp("icon_dedup")
    html_path  = tmp / "icons.html"
    html_path.write_text(HTML, encoding="utf-8")
    db_path    = tmp / "icons.db"
    state_path = tmp / ".state.json"
    asyncio.run(run_pipeline(html_path, db_path, state_path))
    return db_path


@pytest.fixture(scope="module")
def icon_reader(icon_graph):
    db   = kuzu.Database(str(icon_graph), read_only=True)
    conn = kuzu.Connection(db)
    return GraphReader(conn), conn


class TestIconStoredOnceAcrossComponents:
    def test_icon_node_count_is_one_despite_two_uses(self, icon_reader):
        _, conn = icon_reader
        result = conn.execute("MATCH (i:Icon) RETURN count(i)")
        assert result.get_next()[0] == 1

    def test_get_component_expands_marker_back_to_full_svg(self, icon_reader):
        reader, _ = icon_reader
        comp_a = reader.get_component("IconButtonA")
        comp_b = reader.get_component("IconButtonB")
        assert ICON_SVG in comp_a["c.jsx_snippet"]
        assert ICON_SVG in comp_b["c.jsx_snippet"]
        assert "{[icon:" not in comp_a["c.jsx_snippet"]

    def test_get_full_jsx_expands_marker(self, icon_reader):
        reader, _ = icon_reader
        assert ICON_SVG in reader.get_full_jsx("IconButtonA")
