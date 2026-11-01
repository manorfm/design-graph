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


CLAIM = "Tudo o que a tela usa está acima — nada foi cortado."


@pytest.mark.parametrize("marker", ["```", "````", "~~~", "    ```", "// ```"])
def test_assembly_comment_kept_source_and_corrected_only_generated_claim(tmp_path, marker):
    source = f"function Home() {{ /*\n{marker}\n{CLAIM}\n{marker}\n*/ return null; }}"
    path = tmp_path / "comment.js"
    path.write_text(source)
    subprocess.run([os.environ["DG_CAPTURE_NODE"], "--check", str(path)], check=True, timeout=20)

    class Reader:
        def get_screen_assembly(self, name):
            return {"name": "Home", "skeleton": source, "source_lang": "js", "relations": {},
                    "components": [], "data": [], "unread_lists": [], "tokens": [], "resources": [],
                    "actions": [], "states": []}

    result = ToolDispatcher([("doc", Reader())]).dispatch("assemble_page", {"name": "Home"}, "")
    assert source in result
    assert result.count(CLAIM) == 1
    assert COVERAGE_NOTICE in result
    assert "## 8. Completude\n" + COVERAGE_NOTICE in result


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


def test_real_sdk_preserved_comment_bytes_across_all_source_and_assembly_parts(tmp_path):
    import asyncio
    import hashlib
    import json
    import re
    import sys
    from pathlib import Path

    import kuzu
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    from design_graph.capture.binding_capture import BindingCapture
    from design_graph.interface.mcp.assemble_tool import _code_blocks
    from design_graph.interface.mcp.full_tools import source_parts
    from design_graph.model.entities import ExtractedScreen
    from design_graph.model.graph.binding_context import (
        BindingRoot,
        BindingSnapshot,
        write_binding_context,
    )
    from design_graph.model.graph.schema import initialize_schema
    from design_graph.model.graph.writer import GraphWriter

    comment = "\n".join(f"{m}\n{CLAIM}\n{m}" for m in ["```", "````", "~~~", "    ```", "// ```"])
    source = 'function Home() { /*\n' + comment + '\n' + ('preserved comment bytes\n' * 1900) + '*/ return "Fonte não disponível para cliente"; }'
    js = tmp_path / "valid.js"
    js.write_text(source)
    subprocess.run([os.environ["DG_CAPTURE_NODE"], "--check", str(js)], check=True, timeout=20)
    capture = BindingCapture(node=Path(os.environ["DG_CAPTURE_NODE"]), toolchain=Path(os.environ["DG_CAPTURE_ENGINE"]), fingerprint=os.environ["DG_CAPTURE_FINGERPRINT"]).capture(source.encode(), locator="valid.js", source_type="module", syntax="js")
    unit = capture.ir.units[0]
    region = next(r for r in capture.ir.regions if r.slot.value == "function-creation")
    snapshot = BindingSnapshot.create("source-byte-regression", (capture,), (BindingRoot(unit.id, region.id),))
    path = tmp_path / "regression.db"
    db = kuzu.Database(str(path), buffer_pool_size=128 * 1024 * 1024, max_num_threads=2)
    conn = kuzu.Connection(db)
    try:
        initialize_schema(conn)
        writer = GraphWriter(conn)
        writer.write_screen(ExtractedScreen(name="Home", source_code=source, source_lang="js", skeleton=source), [])
        writer.commit()
        revision = write_binding_context(conn, snapshot)
    finally:
        conn.close()
        db.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    server = tmp_path / "server.py"
    server.write_text('''import asyncio,sys,kuzu
from design_graph.model.graph.reader import GraphReader
from design_graph.interface.mcp.server import MCPServer,run_stdio
db=kuzu.Database(sys.argv[1],read_only=True,buffer_pool_size=128*1024*1024,max_num_threads=2)
conn=kuzu.Connection(db)
try: asyncio.run(run_stdio(MCPServer([("fixture",GraphReader(conn))])))
finally: conn.close();db.close()
''')
    qualified = {"db": str(path), "snapshot": revision, "source_selections": [{"unit": unit.id, "region": region.id}]}

    async def exercise():
        params = StdioServerParameters(command=sys.executable, args=["-B", str(server), str(path)], env=dict(os.environ))
        async with stdio_client(params) as streams, ClientSession(*streams) as client:
            await client.initialize()

            async def call(tool, args):
                answer = await asyncio.wait_for(client.call_tool(tool, args), 45)
                assert not answer.is_error
                return "\n".join(c.text for c in answer.content if hasattr(c, "text"))

            outcomes = {}
            for label, tool, args in [
                ("legacy-source", "get_full", {"name": "Home", "aspect": "source"}),
                ("default-assembly", "assemble_page", {"name": "Home"}),
                ("qualified-source", "get_full", {**qualified, "aspect": "source"}),
                ("qualified-assembly", "assemble_page", {**qualified, "name": "Home", "known": ["Home"]}),
            ]:
                first = await call(tool, args)
                match = re.search(r"parte 1/(\d+)", first)
                total = int(match.group(1)) if match else 1
                assert total >= 3
                pages = [first] + [await call(tool, {**args, "part": n}) for n in range(2, total + 1)]
                for n, page in enumerate(pages, 1):
                    assert await call(tool, {**args, "part": n}) == page
                joined = "\n".join(pages)
                if label == "legacy-source":
                    for chunk, _ in source_parts(source):
                        assert chunk in joined
                    assert COVERAGE_NOTICE not in joined
                else:
                    if label.startswith("qualified"):
                        from design_graph.interface.mcp.qualified_pagination import (
                            _plan,
                        )
                        from design_graph.interface.mcp.qualified_source_tool import (
                            _qualified_assembly_sections,
                            _records,
                            _source_sections,
                        )
                        from design_graph.model.graph.reader import GraphReader

                        sections = _source_sections(_records(snapshot, revision, qualified["source_selections"]))
                        heading = "# Qualified source evidence"
                        if tool == "assemble_page":
                            db = kuzu.Database(str(path), read_only=True, buffer_pool_size=128*1024*1024, max_num_threads=2)
                            conn = kuzu.Connection(db)
                            try:
                                sections = _qualified_assembly_sections(GraphReader(conn).get_screen_assembly("Home"), {"Home"}) + sections
                            finally:
                                conn.close(); db.close()
                            heading = "# Montar: Home"
                        planned, _, _ = _plan(sections, heading, COVERAGE_NOTICE, tool)
                        assert all(len(page) <= 20_000 for page in pages)
                        for chunks in planned:
                            for chunk in chunks:
                                assert chunk in joined
                    assert COVERAGE_NOTICE in joined
                assert joined.count(CLAIM) == (10 if label == "qualified-assembly" else 5)
                if tool == "assemble_page":
                    assert "## 8. Completude\n" + COVERAGE_NOTICE in joined
                    if not label.startswith("qualified"):
                        for block in _code_blocks("2. Esqueleto", "## 2. Esqueleto", source, "js"):
                            assert block.text in joined
                outcomes[label] = {"parts": total, "repeats_identical": True, "source_sha256": hashlib.sha256(source.encode()).hexdigest()}
            (tmp_path / "sdk-byte-results.json").write_text(json.dumps(outcomes, indent=2))

    asyncio.run(exercise())
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
