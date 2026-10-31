"""Version 2 static-unit capture profile, not normative runtime environments.

Adds abstract module/script cells and intrinsic arguments to the v1 chain checker.
Host object properties, instantiation, initialization and value facts are not proved.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from hashlib import sha256

from .binding_ir import (
    Binding,
    CheckResult,
    DeclarationKind,
    Envelope,
    EnvironmentKind,
    Namespace,
    _Checker,
    _decode,
    _object,
    canonical_bindings,
)


def binding_id(unit: str, environment: str, name: str) -> str:
    key = json.dumps(
        [unit, environment, "value", name], ensure_ascii=True, separators=(",", ":")
    )
    return "b:" + sha256(key.encode()).hexdigest()


@dataclass(frozen=True)
class IntrinsicBinding:
    binding: str
    environment: str
    unit: str
    kind: str


@dataclass(frozen=True)
class CoverageGap:
    region: str
    kind: str


@dataclass(frozen=True)
class FunctionSite:
    region: str
    kind: str


class _CaptureChecker(_Checker):
    def __init__(self, envelope, intrinsics):
        super().__init__(envelope)
        self.intrinsics = intrinsics

    def canonical_inventory(self):
        # Reuse v1 coexistence checks per canonical group, with explicit v2
        # static-unit and source-name extensions. No occurrence represents a cell.
        groups = defaultdict(list)
        for d in self.e.occurrences:
            groups[d.unit, d.environment, d.name].append(d)
        expected = []
        for (unit, environment, _name), ds in sorted(groups.items()):
            env = self.get(self.envs, unit, environment)
            env, ds = self._normalize_group(env, ds)
            expected.extend(canonical_bindings((env,), tuple(ds)))
        return self._intrinsic_inventory(expected)

    @staticmethod
    def _normalize_group(env, ds):
        kinds = {d.kind for d in ds}
        if kinds & {DeclarationKind.CLASS, DeclarationKind.FUNCTION_NAME}:
            if len(ds) != 1 or env.kind not in (
                EnvironmentKind.ROOT,
                EnvironmentKind.BLOCK,
            ):
                raise ValueError("invalid class/name occurrence")
            ds = [replace(ds[0], kind=DeclarationKind.CONST)]
        if env.kind == EnvironmentKind.ROOT and kinds <= {
            DeclarationKind.VAR,
            DeclarationKind.FUNCTION,
        }:
            env = replace(env, kind=EnvironmentKind.FUNCTION_VAR)
        if env.kind in (EnvironmentKind.BLOCK, EnvironmentKind.CASE) and kinds == {
            DeclarationKind.FUNCTION
        }:
            ds = [replace(d, kind=DeclarationKind.LET) for d in ds]
        return env, ds

    def _intrinsic_inventory(self, expected):
        seen = set()
        for intrinsic in self.intrinsics:
            env = self.get(self.envs, intrinsic.unit, intrinsic.environment)
            if intrinsic.kind != "arguments" or env.kind not in (
                EnvironmentKind.PARAMETERS,
                EnvironmentKind.FUNCTION_SHARED,
            ):
                raise ValueError("invalid intrinsic binding environment/kind")
            id_ = binding_id(intrinsic.unit, env.id, "arguments")
            if (
                intrinsic.binding != id_
                or id_ in seen
                or any(b.id == id_ for b in expected)
            ):
                raise ValueError("duplicate or noncanonical intrinsic binding")
            seen.add(id_)
            expected.append(
                Binding(id_, intrinsic.unit, env.id, Namespace.VALUE, "arguments", ())
            )
        return tuple(expected)


@dataclass(frozen=True)
class BindingCaptureIR:
    version: str
    source_type: str
    syntax: str
    engine_fingerprint: str
    ir: Envelope
    intrinsics: tuple[IntrinsicBinding, ...]
    gaps: tuple[CoverageGap, ...]
    functions: tuple[FunctionSite, ...]

    def check(self) -> CheckResult:
        value = _decode(BindingCaptureIR, asdict(self))
        self._check_profile(value)
        self._check_function_sites(value)
        self._check_gaps(value)
        return _CaptureChecker(value.ir, value.intrinsics).run()

    @staticmethod
    def _check_profile(value):
        if (
            value.version != "binding-capture/2"
            or value.ir.version != "binding-ir/2"
            or value.ir.profile != "static-unit-chain/2"
        ):
            raise ValueError("unsupported capture version/profile")
        if value.source_type not in ("script", "module") or value.syntax not in (
            "js",
            "jsx",
        ):
            raise ValueError("unsupported source kind")
        if len(value.engine_fingerprint) != 64 or any(
            c not in "0123456789abcdef" for c in value.engine_fingerprint
        ):
            raise ValueError("invalid engine fingerprint")
        if len(value.ir.units) != 1:
            raise ValueError("capture requires exactly one whole source unit")

    @staticmethod
    def _check_function_sites(value):
        regions = {r.id: r for r in value.ir.regions}
        sites = {f.region: f for f in value.functions}
        if (
            len(sites) != len(value.functions)
            or set(sites)
            != {r.id for r in value.ir.regions if r.slot.value == "function-creation"}
            or any(f.kind not in ("arrow", "ordinary") for f in value.functions)
        ):
            raise ValueError("incomplete or invalid function site inventory")
        environments = {e.id: e for e in value.ir.environments}
        for intrinsic in value.intrinsics:
            environment = environments.get(intrinsic.environment)
            parameters = regions.get(environment.owner) if environment else None
            site = sites.get(parameters.parent) if parameters else None
            if not site or site.kind != "ordinary":
                raise ValueError("arguments intrinsic requires an ordinary function")

    @staticmethod
    def _check_gaps(value):
        regions = {r.id: r for r in value.ir.regions}
        if len({(g.region, g.kind) for g in value.gaps}) != len(value.gaps):
            raise ValueError("duplicate coverage gap")
        for gap in value.gaps:
            if (
                gap.kind not in ("dynamic-with", "sloppy-direct-eval", "annex-b")
                or gap.region not in regions
                or regions[gap.region].complete
            ):
                raise ValueError("invalid localized coverage gap")
        if {r.id for r in value.ir.regions if not r.complete} != {
            g.region for g in value.gaps
        }:
            raise ValueError("incomplete evaluation region lacks coverage reason")

    def to_json(self) -> str:
        self.check()
        data = asdict(self)
        for key, records in data["ir"].items():
            if isinstance(records, tuple):
                data["ir"][key] = sorted(
                    records, key=lambda r: (r.get("unit", ""), r["id"])
                )
        data["intrinsics"] = sorted(
            data["intrinsics"], key=lambda r: (r["unit"], r["binding"])
        )
        data["gaps"] = sorted(data["gaps"], key=lambda r: (r["region"], r["kind"]))
        data["functions"] = sorted(data["functions"], key=lambda r: r["region"])
        return json.dumps(
            data,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @classmethod
    def from_json(cls, text: str) -> BindingCaptureIR:
        value = _decode(cls, json.loads(text, object_pairs_hook=_object))
        value.check()
        return value
