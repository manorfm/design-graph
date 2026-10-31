"""Normal CLI completion consistency and no-reparse reuse controls."""

import json
import shutil
from pathlib import Path

import pytest

from tests.unit.pipeline.test_binding_cli import build


@pytest.fixture(scope="module")
def baseline(tmp_path_factory):
    root = tmp_path_factory.mktemp("completion")
    source = root / "input.html"
    source.write_text(
        "<html><body><main>General</main><script>const X=1; function f(){return X}</script></body></html>"
    )
    db = root / "new.db"
    result = build(source, db)
    assert result.returncode == 0, result.stderr
    return source, db


@pytest.fixture
def case(tmp_path, baseline):
    source, original = baseline
    db = tmp_path / "new.db"
    for suffix in ("", ".state.json", ".binding.json"):
        shutil.copyfile(str(original) + suffix, str(db) + suffix)
    return source, db


def files(db):
    return {
        suffix: Path(str(db) + suffix).read_bytes()
        for suffix in ("", ".state.json", ".binding.json")
    }


@pytest.mark.parametrize(
    "kind",
    [
        "units",
        "roots",
        "coverage",
        "source_sha256",
        "engine",
        "contract",
        "duplicate",
        "extra",
        "missing",
        "typed",
        "oversized",
        "deep",
        "old",
    ],
)
def test_inconsistent_completion_refused_without_writes(case, kind):
    source, db = case
    path = Path(str(db) + ".binding.json")
    text = path.read_text()
    value = json.loads(text)
    if kind in ("units", "roots", "coverage"):
        value[kind] = []
    elif kind in ("source_sha256", "engine", "contract"):
        value[kind] = "forged"
    elif kind == "extra":
        value["extra"] = 1
    elif kind == "missing":
        del value["units"]
    elif kind == "typed":
        value["coverage"][0]["order"] = False
    elif kind == "old":
        value["contract"] = "binding-build/1"
    if kind == "duplicate":
        text = text.replace('"contract":', '"contract":"forged", "contract":', 1)
    elif kind == "oversized":
        text += " " * (2 * 1024 * 1024)
    elif kind == "deep":
        text = "[" * 65 + "0" + "]" * 65
    else:
        text = json.dumps(value)
    path.write_text(text)
    before = files(db)
    result = build(source, db)
    assert result.returncode != 0 and not result.stdout, result.stdout
    assert files(db) == before


def test_unchanged_reuse_does_not_capture_or_parse(case):
    source, db = case
    before = files(db)
    result = build(
        source,
        db,
        before="""
from design_graph.capture.binding_capture import BindingCapture
def forbidden(*args, **kwargs): raise AssertionError('no-op recaptured')
BindingCapture.capture = forbidden
""",
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "skipped"
    assert files(db) == before


def test_current_adaptor_change_requires_fresh_destination(case, tmp_path):
    source, db = case
    before = files(db)
    from design_graph.capture import binding_capture

    assets = tmp_path / "adaptor"
    shutil.copytree(Path(binding_capture.__file__).with_name("binding_engine"), assets)
    script = assets / "capture.mjs"
    script.write_text(script.read_text() + "\n// harmless changed adaptor bytes\n")
    injection = f"""
from pathlib import Path
from design_graph.capture.binding_capture import BindingCapture
original = BindingCapture.__init__
def changed(self, *args, **kwargs):
 original(self, *args, **kwargs)
 self.assets = Path({str(assets)!r})
BindingCapture.__init__ = changed
"""
    result = build(source, db, before=injection)
    assert result.returncode != 0
    assert files(db) == before
    fresh = tmp_path / "fresh.db"
    result = build(source, fresh, before=injection)
    assert result.returncode == 0, result.stderr
    result = build(source, fresh, before=injection)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "skipped"
