from pathlib import Path

import pytest

from design_graph.core.graph_catalog import (
    AmbiguousGraphSelection,
    GraphCatalog,
    GraphDocumentName,
    GraphSelection,
    GraphSelectionSource,
    UnknownGraphDocument,
)


def _db(root: Path, name: str) -> Path:
    path = root / f"{name}.db"
    path.mkdir()
    return path


class TestGraphDocumentName:
    def test_removes_db_suffix_and_preserves_display_name(self):
        assert GraphDocumentName("Prototype v1.db").value == "Prototype v1"

    def test_rejects_empty_names(self):
        with pytest.raises(ValueError):
            GraphDocumentName("  ")


class TestGraphCatalog:
    def test_discovers_databases_in_stable_name_order(self, tmp_path):
        _db(tmp_path, "zeta")
        _db(tmp_path, "Alpha")
        catalog = GraphCatalog.discover(tmp_path)
        assert [item.name.value for item in catalog.databases] == ["Alpha", "zeta"]

    def test_selects_only_database_automatically(self, tmp_path):
        only = _db(tmp_path, "only")
        selection = GraphCatalog.discover(tmp_path).select(GraphSelection())
        assert selection.database.path == only
        assert selection.source is GraphSelectionSource.ONLY_DATABASE

    def test_requires_explicit_selection_when_multiple_exist(self, tmp_path):
        _db(tmp_path, "one")
        _db(tmp_path, "two")
        with pytest.raises(AmbiguousGraphSelection):
            GraphCatalog.discover(tmp_path).select(GraphSelection())

    def test_explicit_path_has_priority_over_document_name(self, tmp_path):
        one = _db(tmp_path, "one")
        _db(tmp_path, "two")
        selection = GraphCatalog.discover(tmp_path).select(
            GraphSelection(db_path=one, document=GraphDocumentName("two"))
        )
        assert selection.database.path == one
        assert selection.source is GraphSelectionSource.EXPLICIT_PATH

    def test_unknown_document_lists_as_domain_error(self, tmp_path):
        _db(tmp_path, "one")
        with pytest.raises(UnknownGraphDocument):
            GraphCatalog.discover(tmp_path).select(
                GraphSelection(document=GraphDocumentName("missing"))
            )

