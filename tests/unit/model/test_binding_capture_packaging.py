"""Required engine data must not depend on Git-aware build discovery."""

import ast
import re
from fnmatch import fnmatchcase
from pathlib import Path


def test_engine_runtime_assets_are_explicit_package_data():
    root = Path(__file__).parents[3]
    config = (root / "pyproject.toml").read_text()
    section = config.split("[tool.setuptools.package-data]", 1)[1].split("\n[", 1)[0]
    declaration = re.search(r"design_graph\s*=\s*(\[[\s\S]*?\])", section)
    assert declaration is not None
    patterns = ast.literal_eval(declaration.group(1))
    required = {
        "README.md",
        "capture.mjs",
        "engine-api.d.mts",
        "engine-api.mjs",
        "engine-final.patch",
        "package-lock.json",
        "package.json",
        "pin.json",
        "scope-manager-LICENSE",
        "typescript-estree-LICENSE",
    }
    engine = root / "src/design_graph/capture/binding_engine"
    assert {
        p.name for p in engine.iterdir() if p.is_file() and p.suffix != ".py"
    } == required
    missing = sorted(
        name
        for name in required
        if not any(
            fnmatchcase("capture/binding_engine/" + name, pattern)
            for pattern in patterns
        )
    )
    assert not missing, f"archive build lacks declared engine assets: {missing}"
    assert "resources/skills/**/*.md" in patterns
