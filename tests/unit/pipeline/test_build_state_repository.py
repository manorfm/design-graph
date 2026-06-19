from pathlib import Path

from design_graph.pipeline.state import BuildStateRepository
from design_graph.core.models import BuildState


class TestBuildStateRepository:
    def test_state_path_is_owned_by_database(self, tmp_path):
        repository = BuildStateRepository.for_database(tmp_path / "prototype.db")
        assert repository.path == tmp_path / "prototype.db.state.json"

    def test_different_databases_never_share_state(self, tmp_path):
        first = BuildStateRepository.for_database(tmp_path / "first.db")
        second = BuildStateRepository.for_database(tmp_path / "second.db")
        assert first.path != second.path

    def test_force_clear_only_removes_its_own_state(self, tmp_path):
        first = BuildStateRepository.for_database(tmp_path / "first.db")
        second = BuildStateRepository.for_database(tmp_path / "second.db")
        first.path.write_text("{}")
        second.path.write_text("{}")
        first.clear()
        assert not first.path.exists()
        assert second.path.exists()

    def test_migrates_legacy_state_only_when_unambiguous(self, tmp_path):
        legacy = tmp_path / ".graph-state.json"
        legacy.write_text('{"html_hash":"abc"}')
        repository = BuildStateRepository.for_database(tmp_path / "only.db")
        assert repository.migrate_legacy(legacy, known_databases=(tmp_path / "only.db",)) is True
        assert repository.path.exists()
        assert not legacy.exists()

    def test_does_not_migrate_legacy_state_with_multiple_databases(self, tmp_path):
        legacy = tmp_path / ".graph-state.json"
        legacy.write_text("{}")
        repository = BuildStateRepository.for_database(tmp_path / "one.db")
        assert repository.migrate_legacy(
            legacy, known_databases=(tmp_path / "one.db", tmp_path / "two.db")
        ) is False
        assert legacy.exists()

    def test_does_not_give_existing_database_state_to_new_destination(self, tmp_path):
        legacy = tmp_path / ".graph-state.json"
        legacy.write_text("{}")
        repository = BuildStateRepository.for_database(tmp_path / "new.db")
        assert repository.migrate_legacy(
            legacy, known_databases=(tmp_path / "existing.db",)
        ) is False

    def test_persists_database_and_source_identity(self, tmp_path):
        repository = BuildStateRepository.for_database(tmp_path / "one.db")
        state = BuildState("hash", "now", {}, {}, source_path="/src/one.html",
                           database_path="/graphs/one.db", schema_version=2)
        repository.save(state)
        loaded = repository.load()
        assert loaded.source_path == "/src/one.html"
        assert loaded.database_path == "/graphs/one.db"
        assert loaded.schema_version == 2
