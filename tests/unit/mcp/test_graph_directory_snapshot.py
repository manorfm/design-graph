"""
The MCP server opens each *.db file once, at process start, via a read-only
Kuzu connection — it never notices a rebuild written by another process
afterwards (design-graph <html> runs in a separate `design-mcp` client
session). GraphDirectorySnapshot captures "what *.db files exist, with what
mtimes" so MCPServer can tell a rebuilt directory from an unchanged one
without caring *what* changed, only *whether* it did.
"""

from __future__ import annotations

from design_graph.mcp.server import GraphDirectorySnapshot


class TestGraphDirectorySnapshotOf:
    def test_missing_directory_is_empty(self, tmp_path):
        snap = GraphDirectorySnapshot.of(tmp_path / "does_not_exist")
        assert snap.mtime_by_path == {}

    def test_none_directory_is_empty(self):
        assert GraphDirectorySnapshot.of(None).mtime_by_path == {}

    def test_empty_directory_is_empty(self, tmp_path):
        assert GraphDirectorySnapshot.of(tmp_path).mtime_by_path == {}

    def test_lists_each_db_file_with_its_mtime(self, tmp_path):
        db = tmp_path / "proto.db"
        db.write_bytes(b"x")
        snap = GraphDirectorySnapshot.of(tmp_path)
        assert snap.mtime_by_path == {db: db.stat().st_mtime}

    def test_ignores_non_db_files(self, tmp_path):
        (tmp_path / "notes.txt").write_bytes(b"x")
        snap = GraphDirectorySnapshot.of(tmp_path)
        assert snap.mtime_by_path == {}


class TestGraphDirectorySnapshotHasChangedSince:
    def test_identical_snapshots_have_not_changed(self, tmp_path):
        (tmp_path / "proto.db").write_bytes(b"x")
        before = GraphDirectorySnapshot.of(tmp_path)
        after = GraphDirectorySnapshot.of(tmp_path)
        assert after.has_changed_since(before) is False

    def test_new_file_has_changed(self, tmp_path):
        before = GraphDirectorySnapshot.of(tmp_path)
        (tmp_path / "proto.db").write_bytes(b"x")
        after = GraphDirectorySnapshot.of(tmp_path)
        assert after.has_changed_since(before) is True

    def test_removed_file_has_changed(self, tmp_path):
        db = tmp_path / "proto.db"
        db.write_bytes(b"x")
        before = GraphDirectorySnapshot.of(tmp_path)
        db.unlink()
        after = GraphDirectorySnapshot.of(tmp_path)
        assert after.has_changed_since(before) is True

    def test_rewritten_file_has_changed(self, tmp_path):
        db = tmp_path / "proto.db"
        db.write_bytes(b"x")
        before = GraphDirectorySnapshot.of(tmp_path)
        # A rebuild rewrites the same path — simulate the mtime bump directly,
        # since same-second writes on a fast test run can share a timestamp.
        import os
        os.utime(db, (db.stat().st_atime, db.stat().st_mtime + 1))
        after = GraphDirectorySnapshot.of(tmp_path)
        assert after.has_changed_since(before) is True
