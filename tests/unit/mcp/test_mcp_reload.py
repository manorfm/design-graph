"""
MCPServer opens every *.db file once, at construction, over a read-only Kuzu
connection. A read-only handle doesn't observe writes made by another
process afterwards, so a prototype rebuilt by `design-graph <html>` while a
`design-mcp` session is already running stays invisible until the process
restarts — the README says as much ("restart or reconnect ... so the server
reloads the database files"), but nothing enforced it before this. Every
tool call now compares the graph directory's current GraphDirectorySnapshot
against the one taken at last load and reopens only when they differ, so a
long-lived session self-heals instead of silently serving stale data.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from design_graph.mcp.server import MCPServer, _load_readers
from design_graph.pipeline.coordinator import run_pipeline

FIXTURE_DIR = Path(__file__).parent.parent.parent / "fixtures"
SIMPLE_HTML = FIXTURE_DIR / "simple.html"


def _call(server: MCPServer, tool: str, args: dict | None = None):
    return server.dispatch_tool_call(tool, args or {})


def _text(response) -> str:
    return response.text


@pytest.fixture
def graph_dir_with_one_prototype(tmp_path):
    """A real graph directory holding one prototype built from simple.html."""
    asyncio.run(run_pipeline(SIMPLE_HTML, tmp_path / "simple.db", tmp_path / ".state.json"))
    return tmp_path


# ── _load_readers ─────────────────────────────────────────────────────────────

class TestLoadReaders:
    def test_opens_a_reader_per_db_file(self, graph_dir_with_one_prototype):
        readers = _load_readers(graph_dir_with_one_prototype)
        assert [name for name, _ in readers] == ["simple"]

    def test_missing_directory_returns_no_readers(self, tmp_path):
        assert _load_readers(tmp_path / "missing") == []

    def test_corrupt_db_file_is_skipped_not_raised(self, tmp_path):
        (tmp_path / "corrupt.db").write_bytes(b"not a kuzu database")
        assert _load_readers(tmp_path) == []


# ── reload-on-staleness ───────────────────────────────────────────────────────

class TestReloadOnStaleness:
    def test_new_prototype_appears_without_restart(self, tmp_path):
        server = MCPServer([], graph_dir=tmp_path)
        assert "Nenhuma" in _text(_call(server, "list_screens"))

        asyncio.run(run_pipeline(SIMPLE_HTML, tmp_path / "simple.db", tmp_path / ".state.json"))

        assert "RestaurantsPage" in _text(_call(server, "list_screens"))

    def test_removed_prototype_disappears_without_restart(self, graph_dir_with_one_prototype):
        server = MCPServer(
            _load_readers(graph_dir_with_one_prototype), graph_dir=graph_dir_with_one_prototype
        )
        assert "RestaurantsPage" in _text(_call(server, "list_screens"))

        (graph_dir_with_one_prototype / "simple.db").unlink()

        assert "RestaurantsPage" not in _text(_call(server, "list_screens"))

    def test_unchanged_directory_never_reloads(self, graph_dir_with_one_prototype, monkeypatch):
        import design_graph.mcp.server as server_mod
        original = server_mod._load_readers
        calls: list[Path] = []
        monkeypatch.setattr(
            server_mod, "_load_readers",
            lambda d: (calls.append(d), original(d))[1],
        )

        server = MCPServer(
            original(graph_dir_with_one_prototype), graph_dir=graph_dir_with_one_prototype
        )
        for _ in range(3):
            _call(server, "list_screens")
        assert calls == []

    def test_changed_directory_reloads_exactly_once_per_change(
        self, graph_dir_with_one_prototype, monkeypatch
    ):
        import design_graph.mcp.server as server_mod
        original = server_mod._load_readers
        calls: list[Path] = []
        monkeypatch.setattr(
            server_mod, "_load_readers",
            lambda d: (calls.append(d), original(d))[1],
        )

        server = MCPServer(
            original(graph_dir_with_one_prototype), graph_dir=graph_dir_with_one_prototype
        )
        db = graph_dir_with_one_prototype / "simple.db"
        os.utime(db, (db.stat().st_atime, db.stat().st_mtime + 1))

        _call(server, "list_screens")
        _call(server, "list_screens")
        assert len(calls) == 1

    def test_constructing_without_graph_dir_never_touches_the_filesystem(self):
        """Backward-compat: existing tests construct MCPServer(readers) with
        no graph_dir. That path must stay inert, not attempt any reload."""
        server = MCPServer([("stub", object())])
        resp = _call(server, "totally_unknown_tool")
        assert isinstance(resp.text, str)
