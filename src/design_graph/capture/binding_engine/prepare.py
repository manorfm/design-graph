"""Offline reproducible build from explicitly provisioned locked npm packages.

This is a build-time command, never imported or called by the capture provider.
It never installs or downloads dependencies. Output must not exist.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from hashlib import sha256
from pathlib import Path


def prepare(dependencies: Path, output: Path) -> str:
    assets = Path(__file__).parent
    if (
        not dependencies.is_absolute()
        or not dependencies.is_dir()
        or not output.is_absolute()
        or output.exists()
    ):
        raise ValueError(
            "explicit dependency directory and absent absolute output required"
        )
    pin = json.loads((assets / "pin.json").read_text())
    # Verify upstream dependency bytes before any build output. The corrected
    # package is reproduced separately by the maintained unified patch.
    for relative, digest in pin["files"].items():
        if relative.startswith("node_modules/"):
            source = dependencies / relative.removeprefix("node_modules/")
            if (
                not source.is_file()
                or sha256(source.read_bytes()).hexdigest() != digest
            ):
                raise ValueError("locked dependency mismatch: " + relative)
    output.mkdir()
    (output / "node_modules").symlink_to(dependencies, target_is_directory=True)
    corrected = output / "corrected-scope-manager"
    shutil.copytree(dependencies / "@typescript-eslint/scope-manager", corrected)
    for name in (
        "engine-api.mjs",
        "engine-api.d.mts",
        "engine-final.patch",
        "package.json",
        "package-lock.json",
    ):
        shutil.copyfile(assets / name, output / name)
    subprocess.run(
        ["git", "apply", "--check", str(assets / "engine-final.patch")],
        cwd=corrected,
        check=True,
        capture_output=True,
        timeout=10,
    )
    subprocess.run(
        ["git", "apply", str(assets / "engine-final.patch")],
        cwd=corrected,
        check=True,
        capture_output=True,
        timeout=10,
    )
    for relative, digest in pin["files"].items():
        if sha256((output / relative).read_bytes()).hexdigest() != digest:
            raise ValueError("built artifact mismatch: " + relative)
    return sha256(
        json.dumps(pin, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dependencies", required=True, type=Path, help="explicit locked node_modules"
    )
    parser.add_argument(
        "--output", required=True, type=Path, help="absent toolchain directory"
    )
    args = parser.parse_args()
    print(prepare(args.dependencies, args.output))
