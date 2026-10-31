"""Real MCP protocol with explicit lifecycle fault injection, not native facts."""

import hashlib
import json

import pytest

from tests.unit.interface.mcp.test_binding_context_tool import (
    arguments,
    protocol,
)
from tests.unit.interface.mcp.test_binding_context_tool import (
    captured as _captured,
)

captured = _captured  # Explicitly re-export the module-scoped pytest fixture.


@pytest.mark.parametrize("failure", ["none", "open", "connection", "read"])
def test_protocol_readonly_limits_and_deterministic_close(captured, tmp_path, failure):
    db, manifest = captured
    log = tmp_path / "lifecycle.jsonl"
    setup = f"""
import json, kuzu
from pathlib import Path
from design_graph.model import binding_public_context
log = Path({str(log)!r})
def record(value):
 with log.open('a') as stream: stream.write(json.dumps(value)+'\\n')
original_db, original_conn = kuzu.Database, kuzu.Connection
class Database:
 def __init__(self, path, **kwargs):
  record(['open', kwargs])
  if {failure!r} == 'open': raise RuntimeError('injected open error')
  self.inner = original_db(path, **kwargs)
 def close(self):
  self.inner.close(); record(['database.close'])
def connection(db):
 if {failure!r} == 'connection': raise RuntimeError('injected connection error')
 value = original_conn(db.inner)
 close = value.close
 def closing():
  close(); record(['connection.close'])
 value.close = closing
 return value
kuzu.Database, kuzu.Connection = Database, connection
if {failure!r} == 'read':
 def fail(*args, **kwargs): raise ValueError('injected read error')
 binding_public_context.read_project_binding_context = fail
"""

    async def check(client):
        result = await client.call_tool("get_binding_context", arguments(db, manifest))
        assert result.is_error == (failure != "none")

    protocol(check, setup=setup)
    events = [json.loads(line) for line in log.read_text().splitlines()]
    assert events[0] == [
        "open",
        {
            "read_only": True,
            "buffer_pool_size": 128 * 1024 * 1024,
            "max_num_threads": 2,
        },
    ]
    expected = (
        []
        if failure == "open"
        else [["database.close"]]
        if failure == "connection"
        else [["connection.close"], ["database.close"]]
    )
    assert events[1:] == expected


def test_protocol_reported_missing_dependency(captured):
    db, manifest = captured

    async def check(client):
        result = await client.call_tool("get_binding_context", arguments(db, manifest))
        assert result.is_error
        assert "kuzu" in result.content[0].text

    protocol(check, setup="sys.modules['kuzu'] = None")


def test_empty_catalog_stayed_legacy_without_certificate(tmp_path):
    import kuzu

    db = tmp_path / "legacy.db"
    database = kuzu.Database(
        str(db), buffer_pool_size=128 * 1024 * 1024, max_num_threads=2
    )
    database.close()
    before = hashlib.sha256(db.read_bytes()).hexdigest()

    async def check(client):
        result = await client.call_tool(
            "get_binding_context",
            {"db": str(db), "snapshot": "0" * 64, "unit": "u", "region": "r"},
        )
        assert not result.is_error
        data = json.loads(result.content[0].text)
        assert data["availability"] == "legacy/unknown"
        assert data["evidence"] == "legacy"
        assert "root" not in data and "source" not in data

    protocol(check)
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before


def test_legacy_validation_wire_budget_did_not_drift():
    from design_graph.interface.mcp.tool_definitions import MAX_VALIDATION_SOURCE_CHARS
    from design_graph.interface.mcp.validation_tool import (
        MAX_VALIDATION_SOURCE_CHARS as runtime_limit,
    )

    assert MAX_VALIDATION_SOURCE_CHARS == runtime_limit
