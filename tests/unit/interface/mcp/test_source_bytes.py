"""Source bytes are opaque to generated status and coverage prose."""

import os
import subprocess

import pytest

from design_graph.interface.mcp.qualified_source_tool import COVERAGE_NOTICE
from design_graph.interface.mcp.tools import ToolDispatcher

SOURCE = 'function Card() { return "Fonte não disponível para cliente"; }'


class SourceReader:
    def __init__(self, source):
        self.source = source
        self.calls = 0

    def get_full_source(self, name):
        self.calls += 1
        return self.source


def test_successful_source_literal_was_not_missing_status(tmp_path):
    path = tmp_path / "literal.js"
    path.write_text(SOURCE)
    subprocess.run([os.environ["DG_CAPTURE_NODE"], "--check", str(path)], check=True, timeout=20)
    reader = SourceReader({"source_code": SOURCE, "source_lang": "js"})
    result = ToolDispatcher([("doc", reader)]).dispatch(
        "get_full", {"name": "Card", "aspect": "source"}, ""
    )
    assert result == f"# Fonte completo de Card (js)\n\n```js\n{SOURCE}\n```"
    assert COVERAGE_NOTICE not in result
    assert reader.calls == 1


@pytest.mark.parametrize("missing", [None, {}])
def test_structured_absence_did_not_demand_recapture(missing):
    reader = SourceReader(missing)
    result = ToolDispatcher([("doc", reader)]).dispatch(
        "get_full", {"name": "hueFromName", "aspect": "source"}, ""
    )
    assert "Fonte indisponível na busca legada por nome para 'hueFromName'." in result
    assert "não prova ausência de fonte persistida" in result
    assert "--force" not in result
    assert COVERAGE_NOTICE in result
    assert "db/snapshot/source_selections" in result
    assert reader.calls == 1
