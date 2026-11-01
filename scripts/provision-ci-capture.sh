#!/usr/bin/env bash
# CI-only provisioning; the runtime provider remains offline and explicit.
set -euo pipefail
: "${RUNNER_TEMP:?explicit disposable runner directory required}"
: "${GITHUB_ENV:?explicit environment output file required}"
[[ "$(uname -s)-$(uname -m)" == Linux-x86_64 ]] || {
  printf '%s\n' 'Pinned CI Node artifact supports Linux x86_64 only' >&2
  exit 1
}
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
assets="$root/src/design_graph/capture/binding_engine"
work="$(mktemp -d "$RUNNER_TEMP/dg-capture.XXXXXXXX")"
archive=node-v26.7.0-linux-x64.tar.xz
# SHA256 from https://nodejs.org/dist/v26.7.0/SHASUMS256.txt.
# Verify the archive BEFORE extracting or executing any downloaded code.
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
  "https://nodejs.org/dist/v26.7.0/$archive" --output "$work/$archive"
(cd "$work" && printf '%s  %s\n' \
  982aa24dd8be4c889c6a8ab337ddff3b0896645b20f4239356e80552c16277ee \
  "$archive" | sha256sum --check --strict)
tar -xJf "$work/$archive" -C "$work"
node="$work/node-v26.7.0-linux-x64/bin/node"
export PATH="$(dirname "$node"):$PATH"
unset NODE_OPTIONS NODE_PATH
mkdir "$work/dependencies"
cp "$assets/package.json" "$assets/package-lock.json" "$work/dependencies/"
# npm honors the committed integrity lock; never execute package lifecycle hooks.
(cd "$work/dependencies" && "$node" "../node-v26.7.0-linux-x64/lib/node_modules/npm/bin/npm-cli.js" ci --ignore-scripts --no-audit --no-fund)
# Existing recipe checks dependency bytes, applies the exact maintained patch,
# then verifies every corrected toolchain artifact. It performs no downloads.
python "$assets/prepare.py" --dependencies "$work/dependencies/node_modules" \
  --output "$work/engine"
python -I - "$root" "$node" "$work/engine" "$GITHUB_ENV" <<'PY'
import json
import sys
from hashlib import sha256
from pathlib import Path

root, node, engine, destination = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "src"))
from design_graph.capture.binding_capture import BindingCapture

pin = json.loads((root / "src/design_graph/capture/binding_engine/pin.json").read_text())
fingerprint = sha256(json.dumps(pin, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
# Constructor verifies actual Node version and every byte; no source capture.
BindingCapture(node=node, toolchain=engine, fingerprint=fingerprint)
values = {"DG_CAPTURE_NODE": str(node), "DG_CAPTURE_ENGINE": str(engine),
          "DG_CAPTURE_FINGERPRINT": fingerprint}
if any("\n" in value or "\r" in value for value in values.values()):
    raise ValueError("environment values must be single-line")
with destination.open("a") as output:
    for name, value in values.items():
        output.write(f"{name}={value}\n")
print("Verified native capability:", fingerprint, "files:", len(pin["files"]))
PY
