"""The full CI suite must provision, not bypass, native capture admission."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def test_full_ci_provisioned_capture_before_collection():
    workflow = (ROOT / ".github/workflows/tests.yml").read_text()
    provision = "bash scripts/provision-ci-capture.sh"
    assert provision in workflow, "full CI never provisions the required native capability"
    assert workflow.index(provision) < workflow.index("pytest tests/ --cov=")
    script = (ROOT / "scripts/provision-ci-capture.sh").read_text()
    assert "npm-cli.js\" ci --ignore-scripts" in script
    assert "sha256sum --check --strict" in script
    assert "BindingCapture(" in script
    for name in ("DG_CAPTURE_NODE", "DG_CAPTURE_ENGINE", "DG_CAPTURE_FINGERPRINT"):
        assert name in script
    subprocess.run(["bash", "-n", str(ROOT / "scripts/provision-ci-capture.sh")], check=True)
