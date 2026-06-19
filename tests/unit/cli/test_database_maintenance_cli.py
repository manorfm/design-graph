from design_graph.cli.databases import DatabaseCliArgs, run_database_command


class FixedConfirmation:
    def __init__(self, approved: bool) -> None:
        self.approved = approved
        self.calls = 0

    def approve(self, plan) -> bool:
        self.calls += 1
        return self.approved


def _workspace_environment(tmp_path, monkeypatch):
    graph_dir = tmp_path / "graphs"
    config_dir = tmp_path / "config"
    graph_dir.mkdir()
    monkeypatch.setenv("GRAPH_DIR", str(graph_dir))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir))
    monkeypatch.delenv("DESIGN_GRAPH_DOC", raising=False)
    return graph_dir


def test_remove_cancellation_preserves_database(tmp_path, monkeypatch, capsys):
    graph_dir = _workspace_environment(tmp_path, monkeypatch)
    database = graph_dir / "old.db"
    database.mkdir()
    confirmation = FixedConfirmation(False)
    code = run_database_command(
        DatabaseCliArgs(action="remove", document="old"), confirmation
    )
    assert code == 0
    assert confirmation.calls == 1
    assert database.exists()
    assert "Cancelled" in capsys.readouterr().out


def test_force_remove_skips_confirmation_and_deletes_owned_files(tmp_path, monkeypatch):
    graph_dir = _workspace_environment(tmp_path, monkeypatch)
    database = graph_dir / "old.db"
    database.mkdir()
    state = graph_dir / "old.db.state.json"
    state.write_text("{}")
    confirmation = FixedConfirmation(False)
    code = run_database_command(
        DatabaseCliArgs(action="remove", document="old", force=True), confirmation
    )
    assert code == 0
    assert confirmation.calls == 0
    assert not database.exists() and not state.exists()


def test_prune_dry_run_reports_without_deleting(tmp_path, monkeypatch, capsys):
    graph_dir = _workspace_environment(tmp_path, monkeypatch)
    orphan = graph_dir / "missing.db.state.json"
    orphan.write_text("{}")
    confirmation = FixedConfirmation(True)
    code = run_database_command(
        DatabaseCliArgs(action="prune", dry_run=True), confirmation
    )
    assert code == 0
    assert confirmation.calls == 0
    assert orphan.exists()
    assert "Dry run" in capsys.readouterr().out

