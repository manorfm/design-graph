from pathlib import Path
from datetime import timedelta

import pytest

from design_graph.core.graph_catalog import (
    AmbiguousGraphSelection,
    GraphCatalog,
    GraphDocumentName,
    GraphSelection,
    GraphSelectionSource,
    UnknownGraphDocument,
    GraphArtifactKind,
    BuildArtifactRetention,
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


class TestGraphMaintenancePlans:
    def test_removal_plan_owns_database_state_and_build_temp(self, tmp_path):
        database = _db(tmp_path, "old")
        state = tmp_path / "old.db.state.json"
        state.write_text("{}")
        building = tmp_path / ".old.db.building"
        building.mkdir()
        plan = GraphCatalog.discover(tmp_path).plan_removal(GraphDocumentName("old"))
        assert {artifact.kind for artifact in plan.artifacts} == {
            GraphArtifactKind.DATABASE,
            GraphArtifactKind.STATE,
            GraphArtifactKind.BUILD_TEMP,
        }
        result = plan.execute()
        assert result.removed_count == 3
        assert not database.exists() and not state.exists() and not building.exists()

    def test_prune_plan_contains_only_orphan_states_and_build_temps(self, tmp_path):
        _db(tmp_path, "active")
        active_state = tmp_path / "active.db.state.json"
        active_state.write_text("{}")
        orphan_state = tmp_path / "missing.db.state.json"
        orphan_state.write_text("{}")
        building = tmp_path / ".aborted.db.building"
        building.mkdir()
        plan = GraphCatalog.discover(tmp_path).plan_prune(
            retention=BuildArtifactRetention(timedelta(0))
        )
        assert {artifact.path for artifact in plan.artifacts} == {orphan_state, building}

    def test_dry_run_does_not_delete_artifacts(self, tmp_path):
        orphan_state = tmp_path / "missing.db.state.json"
        orphan_state.write_text("{}")
        plan = GraphCatalog.discover(tmp_path).plan_prune()
        result = plan.preview()
        assert result.removed_count == 0
        assert orphan_state.exists()

    def test_prune_preserves_recent_build_temp_by_default(self, tmp_path):
        building = tmp_path / ".active.db.building"
        building.mkdir()
        plan = GraphCatalog.discover(tmp_path).plan_prune()
        assert building not in {artifact.path for artifact in plan.artifacts}
