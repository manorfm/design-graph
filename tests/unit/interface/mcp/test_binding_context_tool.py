"""Qualified companion over the real SDK stdio protocol, never legacy names."""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

COLD_SERVER = """
import importlib.abc, subprocess, sys, asyncio
class Refuse(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, *args):
  if fullname.startswith('design_graph.capture') or (fullname.startswith('design_graph.') and 'parsing' in fullname):
   raise AssertionError('retrieval imported capture/parser: '+fullname)
sys.meta_path.insert(0, Refuse())
def forbidden(*a, **k): raise AssertionError('retrieval launched subprocess')
subprocess.Popen = forbidden
from design_graph.interface.mcp.server import MCPServer, run_stdio
server = MCPServer([])
# TEST_SETUP
asyncio.run(run_stdio(server))
"""


def protocol(check, *, cold=True, setup=""):
    async def run():
        code = COLD_SERVER.replace("# TEST_SETUP", setup)
        if not cold:
            code = code.replace("sys.meta_path.insert(0, Refuse())", "")
        params = StdioServerParameters(
            command=sys.executable,
            args=["-B", "-c", code],
            env={
                **os.environ,
                "PATH": "/no-node",
                "DESIGN_GRAPH_METRICS_DISABLED": "1",
            },
        )
        async with stdio_client(params) as streams, ClientSession(*streams) as client:
            await client.initialize()
            return await check(client)

    return asyncio.run(asyncio.wait_for(run(), timeout=20))


def test_registered_qualified_companion_on_actual_protocol():
    async def check(client):
        tools = (await client.list_tools()).tools
        found = [t for t in tools if t.name == "get_binding_context"]
        assert len(found) == 1, "missing registered qualified binding companion"
        tool = found[0]
        assert tool.annotations.read_only_hint
        assert set(tool.input_schema["required"]) == {
            "db",
            "snapshot",
            "unit",
            "region",
        }
        assert tool.input_schema["additionalProperties"] is False
        assert "expected_sha256" in tool.input_schema["properties"]

    protocol(check, cold=False)


@pytest.fixture(scope="module")
def captured(tmp_path_factory):
    if not all(
        os.environ.get(k)
        for k in ("DG_CAPTURE_NODE", "DG_CAPTURE_ENGINE", "DG_CAPTURE_FINGERPRINT")
    ):
        pytest.skip("requires explicitly pinned reviewed native engine")
    folder = tmp_path_factory.mktemp("qualified")
    source = folder / "qualified.html"
    source.write_text(
        "<html><head><title>Qualified</title></head><body><main>Qualified</main>"
        "<script>const X = 9; function same() { return X; }</script>"
        '<script type="module">const X = 3; function same() { return X; }</script></body></html>'
    )
    db = folder / "qualified.db"
    command = [
        sys.executable,
        "-B",
        "-c",
        "from design_graph.interface.cli.build import main; main()",
        str(source),
        "--db",
        str(db),
        "--json",
        "--binding-node",
        os.environ["DG_CAPTURE_NODE"],
        "--binding-engine",
        os.environ["DG_CAPTURE_ENGINE"],
        "--binding-fingerprint",
        os.environ["DG_CAPTURE_FINGERPRINT"],
    ]
    built = subprocess.run(
        command, check=False, capture_output=True, text=True, timeout=45
    )
    assert built.returncode == 0, built.stderr
    manifest = json.loads(Path(str(db) + ".binding.json").read_text())
    return db, manifest


def arguments(db, manifest, root=None):
    root = root or manifest["roots"][0]
    return {
        "db": str(db),
        "snapshot": manifest["snapshot"],
        "unit": root["unit"],
        "region": root["region"],
    }


def test_cold_protocol_equaled_normal_cli_for_every_qualified_root(captured):
    db, manifest = captured
    before = hashlib.sha256(db.read_bytes()).hexdigest()

    async def check(client):
        for root in manifest["roots"]:
            args = arguments(db, manifest, root)
            result = await client.call_tool("get_binding_context", args)
            assert not result.is_error, result
            text = result.content[0].text
            cmd = [
                sys.executable,
                "-B",
                "-c",
                "from design_graph.interface.cli.query import main; main()",
                "binding-context",
                "--db",
                str(db),
                "--snapshot",
                args["snapshot"],
                "--unit",
                args["unit"],
                "--region",
                args["region"],
            ]
            cli = await asyncio.to_thread(
                subprocess.run,
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=45,
            )
            assert cli.returncode == 0, cli.stderr
            assert text + "\n" == cli.stdout
            data = json.loads(text)
            assert data["evidence"] == "IR_ONLY"
            assert data["initialization"] == data["value"] == "unknown"
            assert data["source"]["unit"] == root["unit"]
            assert "source_code" not in data
        good = await client.call_tool(
            "get_binding_context", {**args, "expected_sha256": manifest["snapshot"]}
        )
        assert not good.is_error
        bad = await client.call_tool(
            "get_binding_context", {**args, "expected_sha256": "0" * 64}
        )
        assert bad.is_error
        for changes in (
            {"snapshot": "f" * 64},
            {"unit": "unknown"},
            {"region": "unknown"},
        ):
            assert (
                await client.call_tool("get_binding_context", {**args, **changes})
            ).is_error

    protocol(check)
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before


@pytest.mark.parametrize(
    "changes",
    [
        {"unit": None},
        {"unit": ""},
        {"region": 1},
        {"snapshot": True},
        {"snapshot": "a" * 4097},
        {"region": "r" * 4097},
        {"expected_sha256": "A" * 64},
        {"expected_sha256": "abc"},
        {"db": "relative.db"},
        {"name": "same"},
        {"doc": "same"},
        {"unit": "unit\x00bad"},
    ],
)
def test_invalid_arguments_failed_before_opening_database(tmp_path, changes):
    missing = tmp_path / "absent.db"
    args = {"db": str(missing), "snapshot": "s", "unit": "u", "region": "r", **changes}

    async def check(client):
        result = await client.call_tool("get_binding_context", args)
        assert result.is_error
        assert "invalid binding context arguments" in result.content[0].text

    protocol(check)
    assert not missing.exists()


def test_missing_database_did_not_initialize_it(tmp_path):
    missing = tmp_path / "missing.db"

    async def check(client):
        result = await client.call_tool(
            "get_binding_context",
            {"db": str(missing), "snapshot": "s", "unit": "u", "region": "r"},
        )
        assert result.is_error

    protocol(check)
    assert not missing.exists()
