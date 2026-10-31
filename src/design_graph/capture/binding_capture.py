"""Explicit pinned whole-unit producer; never installs/discovers a toolchain."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from design_graph.model.binding_capture_ir import (
    BindingCaptureIR,
    CoverageGap,
    FunctionSite,
    IntrinsicBinding,
    _CaptureChecker,
    binding_id,
)
from design_graph.model.binding_ir import (
    Binding,
    DeclarationOccurrence,
    Envelope,
    Environment,
    EvaluationRegion,
    Namespace,
    Reference,
    Resolution,
    ResolutionState,
    SourceUnit,
    _decode,
)


class BindingCapture:
    def __init__(self, *, node: Path, toolchain: Path, fingerprint: str):
        self.node, self.toolchain = Path(node), Path(toolchain)
        self.assets = Path(__file__).with_name("binding_engine")
        self.pin = json.loads((self.assets / "pin.json").read_text())
        pin = self.pin
        expected = sha256(
            json.dumps(pin, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if fingerprint != expected:
            raise ValueError("wrong explicit engine fingerprint")
        if (
            not self.node.is_absolute()
            or not self.node.is_file()
            or not self.toolchain.is_absolute()
            or not self.toolchain.is_dir()
        ):
            raise ValueError("explicit absolute node/toolchain paths required")
        self.env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("NODE_OPTIONS", "NODE_PATH")
        }
        self._verify_toolchain()
        self.fingerprint = fingerprint

    def _verify_toolchain(self):
        pin = self.pin
        version = subprocess.run(
            [str(self.node), "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
            env=self.env,
        )
        if version.stdout.strip() != pin["node_version"]:
            raise ValueError("wrong pinned Node version")
        for relative, digest in pin["files"].items():
            path = self.toolchain / relative
            if not path.is_file() or sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("toolchain artifact mismatch: " + relative)

    def capture(
        self, source: bytes, *, locator: str, source_type: str, syntax: str
    ) -> BindingCaptureIR:
        if type(source) is not bytes or len(source) > 1024 * 1024:
            raise ValueError("whole unit must be UTF8 bytes, at most 1 MiB")
        if (
            source_type not in ("script", "module")
            or syntax not in ("js", "jsx")
            or not locator
        ):
            raise ValueError("explicit supported locator/source_type/syntax required")
        text = source.decode("utf8", errors="strict")
        self._verify_toolchain()
        raw = self._capture_native(text, source_type, syntax)
        ir, intrinsics = self._inventory(raw, source, locator, source_type, syntax)
        ir = self._project_references(ir, raw["references"], intrinsics)
        captured = BindingCaptureIR(
            "binding-capture/2",
            source_type,
            syntax,
            self.fingerprint,
            ir,
            intrinsics,
            tuple(_decode(CoverageGap, g) for g in raw["gaps"]),
            tuple(_decode(FunctionSite, f) for f in raw["functions"]),
        )
        captured.check()  # Independently recomputes first-binding lookup in Python.
        return captured

    def _capture_native(self, text, source_type, syntax):
        request = {
            "source": text,
            "source_type": source_type,
            "syntax": syntax,
            "engine": str(self.toolchain),
        }
        result = subprocess.run(
            [str(self.node), str(self.assets / "capture.mjs")],
            input=json.dumps(request),
            capture_output=True,
            check=False,
            text=True,
            timeout=20,
            env=self.env,
        )
        if result.returncode:
            raise ValueError("engine capture refused: " + result.stderr[-4000:])
        if len(result.stdout) > 64 * 1024 * 1024:
            raise ValueError("capture output limit")
        return json.loads(result.stdout)

    @staticmethod
    def _inventory(raw, source, locator, source_type, syntax):
        text = source.decode("utf8", errors="strict")
        unit = (
            "u:"
            + sha256(
                json.dumps(
                    [locator, source_type, syntax, sha256(source).hexdigest()],
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
        )
        qualify = lambda row: {"unit": unit, **row}
        envs = tuple(_decode(Environment, qualify(e)) for e in raw["environments"])
        regions = tuple(_decode(EvaluationRegion, qualify(r)) for r in raw["regions"])
        occurrences = tuple(
            _decode(DeclarationOccurrence, qualify(d)) for d in raw["occurrences"]
        )
        bindings = tuple(
            Binding(
                binding_id(unit, v["environment"], v["name"]),
                unit,
                v["environment"],
                Namespace.VALUE,
                v["name"],
                tuple(sorted(v["occurrences"])),
            )
            for v in raw["variables"]
        )
        intrinsics = tuple(
            IntrinsicBinding(
                binding_id(unit, i["environment"], "arguments"),
                i["environment"],
                unit,
                i["kind"],
            )
            for i in raw["intrinsics"]
        )
        ir = Envelope(
            "binding-ir/2",
            "static-unit-chain/2",
            (
                SourceUnit(
                    unit,
                    locator,
                    text,
                    sha256(source).hexdigest(),
                    len(source),
                    regions[0].id,
                ),
            ),
            envs,
            regions,
            occurrences,
            bindings,
            (),
            (),
        )
        return ir, intrinsics

    @staticmethod
    def _target_path(origin, target_environment, environments):
        path, cursor = [], origin
        while cursor is not None:
            path.append(cursor)
            if cursor == target_environment:
                break
            cursor = environments[cursor].outer
        if target_environment and cursor is None:
            raise ValueError("native target outside derived evaluation chain")
        return tuple(path)

    def _project_references(self, ir, native_references, intrinsics):
        checker = _CaptureChecker(ir, intrinsics)
        checker.source_units()
        checker.topology()
        references, resolutions = [], []
        unit = ir.units[0].id
        env_by_id = {e.id: e for e in ir.environments}
        for row in native_references:
            row = dict(row)
            target_key = row.pop("target")
            ref = _decode(Reference, {"unit": unit, **row})
            origin, complete = checker.origin(unit, ref.region)
            target = binding_id(unit, *target_key) if target_key else None
            path = self._target_path(
                origin, target_key[0] if target_key else None, env_by_id
            )
            state = ResolutionState.RESOLVED if target else ResolutionState.UNRESOLVED
            if not complete:
                state, target, path = ResolutionState.UNKNOWN, None, []
            references.append(ref)
            resolutions.append(
                Resolution(ref.id, unit, state, origin, target, tuple(path))
            )
        return replace(ir, references=tuple(references), resolutions=tuple(resolutions))
