# T12 — GraphDiff

**Fase**: 3 — Graph
**Arquivo**: `src/design_graph/graph/diff.py`
**Depende de**: `core/models.py` (ExtractedScreen), nada mais
**Bloqueia**: T13 (PipelineCoordinator)

---

## Contrato

```python
@dataclass
class BuildState:
    html_hash: str
    last_build: str           # ISO datetime string
    screens: dict[str, str]   # name → content hash
    components: dict[str, int]  # name → occurrence count

@dataclass
class BuildDiff:
    is_first_build: bool
    screens_added: list[str]
    screens_removed: list[str]
    comps_added: list[str]
    comps_removed: list[str]

def load_state(state_path: Path) -> BuildState: ...
def save_state(state_path: Path, state: BuildState) -> None: ...

def compute_diff(
    prev: BuildState,
    screens: list[ExtractedScreen],
    comps: Counter,
) -> BuildDiff: ...

def compute_screen_hash(screen: ExtractedScreen) -> str: ...
```

---

## TDD

Estes testes são migração direta dos `test_build.py::TestDiffState` existentes,
com adaptações para o novo dataclass.

```python
# tests/unit/graph/test_diff.py

class TestLoadState:
    def test_returns_empty_state_for_missing_file(self, tmp_path):
        state = load_state(tmp_path / "nonexistent.json")
        assert state.html_hash == ""
        assert state.screens == {}
        assert state.components == {}

    def test_loads_existing_state(self, tmp_path):
        data = {
            "html_hash": "abc123",
            "last_build": "2024-01-01T00:00:00",
            "screens": {"A": "hash_a"},
            "components": {"BtnPrimary": 3},
        }
        path = tmp_path / "state.json"
        path.write_text(json.dumps(data))
        state = load_state(path)
        assert state.html_hash == "abc123"
        assert state.screens == {"A": "hash_a"}

    def test_returns_empty_state_for_malformed_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json {{{")
        state = load_state(path)
        assert state.html_hash == ""


class TestSaveState:
    def test_creates_file(self, tmp_path):
        state = BuildState(html_hash="abc", last_build="2024",
                           screens={}, components={})
        path = tmp_path / "state.json"
        save_state(path, state)
        assert path.exists()

    def test_creates_parent_directory(self, tmp_path):
        state = BuildState(html_hash="abc", last_build="2024",
                           screens={}, components={})
        path = tmp_path / "subdir" / "state.json"
        save_state(path, state)
        assert path.exists()

    def test_roundtrip(self, tmp_path):
        original = BuildState(
            html_hash="xyz", last_build="2024-01-01",
            screens={"Page": "hash_p"}, components={"Btn": 2}
        )
        path = tmp_path / "state.json"
        save_state(path, original)
        loaded = load_state(path)
        assert loaded.html_hash == original.html_hash
        assert loaded.screens == original.screens


class TestComputeDiff:
    def test_first_build_when_no_previous_hash(self):
        prev = BuildState(html_hash="", last_build="",
                          screens={}, components={})
        diff = compute_diff(prev, [], Counter())
        assert diff.is_first_build is True

    def test_not_first_build_when_previous_hash_exists(self):
        prev = BuildState(html_hash="abc", last_build="",
                          screens={}, components={})
        diff = compute_diff(prev, [], Counter())
        assert diff.is_first_build is False

    def test_screens_added_detected(self):
        prev = BuildState(html_hash="abc", last_build="",
                          screens={"A": "x"}, components={})
        new_screens = [
            ExtractedScreen(name="A", component_refs=[], sections_count=0),
            ExtractedScreen(name="B", component_refs=[], sections_count=0),
        ]
        diff = compute_diff(prev, new_screens, Counter())
        assert "B" in diff.screens_added
        assert "A" not in diff.screens_added

    def test_screens_removed_detected(self):
        prev = BuildState(html_hash="abc", last_build="",
                          screens={"A": "x", "B": "y"}, components={})
        new_screens = [
            ExtractedScreen(name="A", component_refs=[], sections_count=0),
        ]
        diff = compute_diff(prev, new_screens, Counter())
        assert "B" in diff.screens_removed

    def test_comps_added_detected(self):
        prev = BuildState(html_hash="abc", last_build="",
                          screens={}, components={"BtnPrimary": 2})
        diff = compute_diff(prev, [], Counter({"BtnPrimary": 2, "NewCard": 1}))
        assert "NewCard" in diff.comps_added

    def test_comps_removed_detected(self):
        prev = BuildState(html_hash="abc", last_build="",
                          screens={}, components={"OldComp": 1, "Btn": 2})
        diff = compute_diff(prev, [], Counter({"Btn": 2}))
        assert "OldComp" in diff.comps_removed


class TestComputeScreenHash:
    def test_same_screen_same_hash(self):
        screen = ExtractedScreen(name="A", component_refs=["Btn"], sections_count=0)
        assert compute_screen_hash(screen) == compute_screen_hash(screen)

    def test_different_refs_different_hash(self):
        a = ExtractedScreen(name="A", component_refs=["Btn"], sections_count=0)
        b = ExtractedScreen(name="A", component_refs=["Modal"], sections_count=0)
        assert compute_screen_hash(a) != compute_screen_hash(b)
```

---

## Done when

- [x] Todos os testes passam (incluindo os migrados do legado)
- [x] `compute_diff` não toca em arquivo nem em Kuzu — pura
- [x] `save_state` cria o diretório pai se necessário
