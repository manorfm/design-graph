"""Standalone binding IR groundwork; no capture, database or public integration.

The finite profile models declarative lexical chains, not host/global objects,
imports, eval, with, Annex B or TS declaration merging. Typed evaluation slots
are producer assertions, not an AST authenticated by this checker. Even exact
source bytes plus a same-payload hash cannot authenticate a coherent rewrite.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass, fields, is_dataclass, replace
from enum import Enum
from hashlib import sha256
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints


class Namespace(str, Enum):
    VALUE = "value"
    TYPE = "type"  # Recognized but unsupported by lexical-chain/1.


class DeclarationKind(str, Enum):
    VAR = "var"
    FUNCTION = "function"
    LET = "let"
    CONST = "const"
    PARAMETER = "parameter"
    CLASS = "class"
    FUNCTION_NAME = "function-name"


class EnvironmentKind(str, Enum):
    ROOT = "root"
    BLOCK = "block"
    CASE = "case"
    PARAMETERS = "parameters"
    FUNCTION_VAR = "function-var"
    FUNCTION_SHARED = "function-shared"


@dataclass(frozen=True)
class SourceUnit:
    id: str
    locator: str
    source: str
    source_sha256: str
    byte_length: int
    root_region: str


@dataclass(frozen=True)
class Environment:
    id: str
    unit: str
    kind: EnvironmentKind
    owner: str
    outer: str | None
    complete: bool


@dataclass(frozen=True)
class DeclarationOccurrence:
    id: str
    unit: str
    environment: str
    namespace: Namespace
    name: str
    kind: DeclarationKind
    start: int
    end: int


@dataclass(frozen=True)
class Binding:
    id: str
    unit: str
    environment: str
    namespace: Namespace
    name: str
    occurrences: tuple[str, ...]


def canonical_bindings(
    environments: tuple[Environment, ...],
    occurrences: tuple[DeclarationOccurrence, ...],
) -> tuple[Binding, ...]:
    """Group only permitted declarations; no representative occurrence wins.

    Multiple function declarations and duplicate parameters are deliberately
    refused in this finite profile: their instantiation rules are not modeled.
    Parameter + var shares a cell only in FUNCTION_SHARED (no expressions).
    """
    environments = tuple(_decode(Environment, asdict(e)) for e in environments)
    occurrences = tuple(_decode(DeclarationOccurrence, asdict(d)) for d in occurrences)
    envs = {(e.unit, e.id): e for e in environments}
    if len(envs) != len(environments):
        raise ValueError("duplicate environment")
    groups = defaultdict(list)
    seen = set()
    for d in occurrences:
        if (d.unit, d.id) in seen:
            raise ValueError("duplicate declaration occurrence")
        seen.add((d.unit, d.id))
        if d.namespace != Namespace.VALUE or not d.name:
            raise ValueError("unsupported namespace or empty decoded name")
        if (d.unit, d.environment) not in envs:
            raise ValueError("declaration environment absent from unit")
        groups[d.unit, d.environment, d.namespace, d.name].append(d)
    result = []
    for (unit, environment, namespace, name), ds in sorted(groups.items()):
        kind = envs[unit, environment].kind
        kinds = [d.kind for d in ds]
        var_env = kind in (
            EnvironmentKind.FUNCTION_VAR,
            EnvironmentKind.FUNCTION_SHARED,
        )
        if (
            any(k in (DeclarationKind.VAR, DeclarationKind.FUNCTION) for k in kinds)
            and not var_env
        ):
            raise ValueError("var/function requires a modeled function environment")
        if DeclarationKind.PARAMETER in kinds and kind not in (
            EnvironmentKind.PARAMETERS,
            EnvironmentKind.FUNCTION_SHARED,
        ):
            raise ValueError("parameter in non-parameter environment")
        if any(
            k in (DeclarationKind.LET, DeclarationKind.CONST) for k in kinds
        ) and kind in (
            EnvironmentKind.PARAMETERS,
            EnvironmentKind.FUNCTION_VAR,
            EnvironmentKind.FUNCTION_SHARED,
        ):
            raise ValueError("lexical declaration requires a lexical environment")
        if len(ds) > 1:
            allowed = {DeclarationKind.VAR, DeclarationKind.FUNCTION}
            if kind == EnvironmentKind.FUNCTION_SHARED:
                allowed.add(DeclarationKind.PARAMETER)
            if (
                not set(kinds) <= allowed
                or kinds.count(DeclarationKind.FUNCTION) > 1
                or kinds.count(DeclarationKind.PARAMETER) > 1
            ):
                raise ValueError("illegal or unsupported declaration coexistence")
        key = json.dumps(
            [unit, environment, namespace, name],
            ensure_ascii=True,
            separators=(",", ":"),
        )
        id = "b:" + sha256(key.encode("utf-8")).hexdigest()
        result.append(
            Binding(
                id, unit, environment, namespace, name, tuple(sorted(d.id for d in ds))
            )
        )
    return tuple(result)


def _decode(type_: Any, value: Any) -> Any:
    """Decode every value exactly, reusing only invocation-local schema facts.

    Schema entries are immutable field-name/type tuples, never admitted payloads.
    Each independent transport decode starts with a fresh schema inventory.
    """
    schemas = {}

    def visit(expected, item):
        origin, args = get_origin(expected), get_args(expected)
        if origin in (Union, UnionType):
            for choice in args:
                try:
                    return visit(choice, item)
                except ValueError:
                    pass
            raise ValueError("invalid optional field")
        if expected is type(None):
            if item is None:
                return None
            raise ValueError("expected null")
        if origin is tuple:
            if not isinstance(item, (list, tuple)):
                raise ValueError("expected array")
            return tuple(visit(args[0], child) for child in item)
        if isinstance(expected, type) and issubclass(expected, Enum):
            try:
                return expected(item)
            except (ValueError, TypeError):
                raise ValueError("unknown enum value") from None
        if is_dataclass(expected):
            if expected not in schemas:
                hints = get_type_hints(expected)
                field_types = tuple(
                    (field.name, hints[field.name]) for field in fields(expected)
                )
                schemas[expected] = (frozenset(name for name, _ in field_types), field_types)
            names, field_types = schemas[expected]
            if type(item) is not dict or set(item) != names:
                raise ValueError("missing or unknown record fields")
            return expected(**{name: visit(kind, item[name]) for name, kind in field_types})
        if type(item) is not expected:
            raise ValueError("incorrect scalar type")
        return item

    return visit(type_, value)


def _validate_typed(type_: Any, value: Any) -> None:
    """Check exact field types AND deep immutability without copying the IR.

    This is not an origin/authenticity check. Type-hint memoization lives only
    within this traversal; no accepted value survives into another invocation.
    Transport callers use _decode instead, which already constructs exact types.
    """
    hints = {}

    def visit(expected, item):
        origin, args = get_origin(expected), get_args(expected)
        if origin in (Union, UnionType):
            for choice in args:
                try:
                    visit(choice, item)
                    return
                except ValueError:
                    pass
            raise ValueError("invalid optional field")
        if origin is tuple:
            if type(item) is not tuple:
                raise ValueError("expected immutable tuple")
            if len(args) == 2 and args[1] is Ellipsis:
                for child in item:
                    visit(args[0], child)
            else:
                if len(item) != len(args):
                    raise ValueError("incorrect tuple arity")
                for child_type, child in zip(args, item):
                    visit(child_type, child)
            return
        if is_dataclass(expected):
            if type(item) is not expected or not expected.__dataclass_params__.frozen:
                raise ValueError("expected exact frozen record")
            if expected not in hints:
                hints[expected] = get_type_hints(expected)
            for field in fields(expected):
                visit(hints[expected][field.name], getattr(item, field.name))
            return
        if type(item) is not expected:
            raise ValueError("incorrect scalar or enum type")

    visit(type_, value)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


class EvaluationSlot(str, Enum):
    ROOT = "root"
    EVALUATION = "evaluation"
    BLOCK = "block"
    SWITCH = "switch"
    SWITCH_DISCRIMINANT = "switch-discriminant"
    SWITCH_CASE = "switch-case"
    FUNCTION_CREATION = "function-creation"
    FUNCTION_PARAMETERS = "function-parameters"
    FUNCTION_BODY = "function-body"
    PARAMETER_DEFAULT = "parameter-default"
    PARAMETER_COMPUTED = "parameter-computed"
    FUNCTION_NAME = "function-name"
    CLASS = "class"
    CATCH = "catch"
    CATCH_BODY = "catch-body"


class AccessKind(str, Enum):
    READ = "read"
    WRITE = "write"
    READ_WRITE = "read-write"


class ResolutionState(str, Enum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    UNKNOWN = "unknown"


class InitializationStatus(str, Enum):
    UNKNOWN = "unknown"  # No flow/instantiation analysis is implemented here.


class ValueStatus(str, Enum):
    UNKNOWN = "unknown"


class EvidenceStatus(str, Enum):
    IR_ONLY = "ir-only"
    CAPTURE_ATTESTED = "capture-attested"
    SOURCE_CHECKED = "source-checked"


@dataclass(frozen=True)
class EvaluationRegion:
    id: str
    unit: str
    slot: EvaluationSlot
    parent: str | None
    environment: str | None
    start: int
    end: int
    split_parameters: bool | None
    complete: bool


@dataclass(frozen=True)
class Reference:
    id: str
    unit: str
    region: str
    namespace: Namespace
    name: str
    access: AccessKind
    start: int
    end: int


@dataclass(frozen=True)
class Resolution:
    id: str  # Same local ID as the reference; qualified by unit.
    unit: str
    state: ResolutionState
    origin: str
    target: str | None
    path: tuple[str, ...]


@dataclass(frozen=True)
class CheckResult:
    resolutions: tuple[Resolution, ...]
    evidence: EvidenceStatus = EvidenceStatus.IR_ONLY
    initialization: InitializationStatus = InitializationStatus.UNKNOWN
    value: ValueStatus = ValueStatus.UNKNOWN


@dataclass(frozen=True)
class AdmissionReceipt:
    """Caller-trusted admission assertion, NEVER a field in the IR payload.

    The caller must obtain this from an independently retained trusted admission
    channel. Constructing it with a digest read from the same mutable payload
    supplies NO authenticity. This class neither signs nor verifies provenance;
    source-checked means the caller attests an external source check occurred.
    No real admission channel is implemented or exercised by this module.
    """

    expected_sha256: str
    evidence: EvidenceStatus
    authority: str


@dataclass(frozen=True)
class Envelope:
    version: str
    profile: str
    units: tuple[SourceUnit, ...]
    environments: tuple[Environment, ...]
    regions: tuple[EvaluationRegion, ...]
    occurrences: tuple[DeclarationOccurrence, ...]
    bindings: tuple[Binding, ...]
    references: tuple[Reference, ...]
    resolutions: tuple[Resolution, ...]

    @classmethod
    def from_json(cls, text: str) -> Envelope:
        try:
            data = json.loads(text, object_pairs_hook=_object)
            envelope = _decode(cls, data)
        except (TypeError, RecursionError, UnicodeError) as exc:
            raise ValueError("invalid IR JSON") from exc
        envelope.validate()
        return envelope

    def validate(self) -> None:
        self.check()

    def check(self, receipt: AdmissionReceipt | None = None) -> CheckResult:
        envelope = _decode(Envelope, asdict(self))
        if envelope.version != "binding-ir/1" or envelope.profile != "lexical-chain/1":
            raise ValueError("unsupported version or profile")
        if any(
            d.kind in (DeclarationKind.CLASS, DeclarationKind.FUNCTION_NAME)
            for d in envelope.occurrences
        ) or any(
            r.slot
            in (
                EvaluationSlot.CLASS,
                EvaluationSlot.FUNCTION_NAME,
                EvaluationSlot.CATCH,
                EvaluationSlot.CATCH_BODY,
            )
            for r in envelope.regions
        ):
            raise ValueError("capture-only extension requires version 2")
        result = _Checker(envelope).run()
        if receipt is not None:
            if not isinstance(receipt, AdmissionReceipt):
                raise ValueError("expected caller-trusted admission receipt")
            admitted: AdmissionReceipt = _decode(AdmissionReceipt, asdict(receipt))
            if (
                admitted.evidence
                not in (EvidenceStatus.CAPTURE_ATTESTED, EvidenceStatus.SOURCE_CHECKED)
                or not admitted.authority
                or admitted.expected_sha256 != envelope.digest()
            ):
                raise ValueError("invalid or mismatching external admission receipt")
            result = replace(result, evidence=admitted.evidence)
        return result

    def digest(self) -> str:
        """Canonical IR commitment, not a source authenticity certificate."""
        return sha256(self.to_json().encode("utf-8")).hexdigest()

    def to_json(self) -> str:
        # Revalidate direct constructors too, not only decoded transport.
        envelope = _decode(Envelope, asdict(self))
        envelope.validate()
        data = asdict(envelope)
        for name in (
            "units",
            "environments",
            "regions",
            "occurrences",
            "bindings",
            "references",
            "resolutions",
        ):
            data[name] = sorted(
                data[name], key=lambda x: (x.get("unit", ""), x.get("id", ""))
            )
        return json.dumps(
            data,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )


def _index(records):
    result = {}
    for record in records:
        if not record.id or len(record.id) > 256:
            raise ValueError("invalid record identity")
        key = (record.unit, record.id)
        if key in result:
            raise ValueError("duplicate qualified record identity")
        result[key] = record
    return result


class _Checker:
    def __init__(self, envelope: Envelope):
        self.e = envelope
        self.units = {u.id: u for u in envelope.units}
        if len(self.units) != len(envelope.units) or any(
            not u.id for u in envelope.units
        ):
            raise ValueError("duplicate or empty source unit")
        self.envs = _index(envelope.environments)
        self.regions = _index(envelope.regions)
        # Qualified child inventories stay local to this semantic admission.
        self.function_children = defaultdict(list)
        for region in envelope.regions:
            self.function_children[region.unit, region.parent, region.slot].append(
                region
            )
        self.refs = _index(envelope.references)
        self.resolutions = _index(envelope.resolutions)
        self.bindings = _index(envelope.bindings)
        _index(envelope.occurrences)
        self.origins = {}
        self.active = set()
        self.boundaries = {}

    def get(self, table, unit, id):
        try:
            return table[unit, id]
        except KeyError:
            raise ValueError("record absent from qualified unit") from None

    def span(self, record):
        if record.unit not in self.boundaries:
            raise ValueError("unknown source unit")
        if (
            record.start not in self.boundaries[record.unit]
            or record.end not in self.boundaries[record.unit]
            or record.start > record.end
        ):
            raise ValueError("invalid UTF8 byte bounds")

    def source_units(self):
        for u in self.e.units:
            raw = u.source.encode("utf-8")
            if (
                not u.locator
                or u.byte_length != len(raw)
                or sha256(raw).hexdigest() != u.source_sha256
            ):
                raise ValueError("source metadata mismatch")
            offsets, offset = {0}, 0
            for char in u.source:
                offset += len(char.encode("utf-8"))
                offsets.add(offset)
            self.boundaries[u.id] = offsets
            root = self.get(self.regions, u.id, u.root_region)
            if root.slot != EvaluationSlot.ROOT or (root.start, root.end) != (
                0,
                len(raw),
            ):
                raise ValueError("invalid source root")

    def topology(self):
        for e in self.envs.values():
            self.get(self.regions, e.unit, e.owner)
            seen = set()
            current = e
            while current is not None:
                k = current.unit, current.id
                if k in seen or len(seen) >= 256:
                    raise ValueError("cyclic or overdeep environment chain")
                seen.add(k)
                current = (
                    self.get(self.envs, e.unit, current.outer)
                    if current.outer is not None
                    else None
                )
        for r in self.e.regions:
            self.span(r)
            seen = set()
            cursor = r
            while cursor is not None:
                if cursor.id in seen or len(seen) >= 256:
                    raise ValueError("cyclic or overdeep evaluation region chain")
                seen.add(cursor.id)
                cursor = (
                    self.get(self.regions, r.unit, cursor.parent)
                    if cursor.parent is not None
                    else None
                )
            if r.parent is not None:
                parent = self.get(self.regions, r.unit, r.parent)
                if not parent.start <= r.start <= r.end <= parent.end:
                    raise ValueError("region outside parent bounds")
            self.origin(r.unit, r.id)
        for e in self.e.environments:
            owner = self.get(self.regions, e.unit, e.owner)
            if owner.environment != e.id:
                raise ValueError("environment is not owned by its region")
        for r in self.e.regions:
            if r.slot == EvaluationSlot.SWITCH:
                children = [
                    c.slot
                    for c in self.e.regions
                    if c.unit == r.unit and c.parent == r.id
                ]
                if (
                    children.count(EvaluationSlot.SWITCH_CASE) != 1
                    or children.count(EvaluationSlot.SWITCH_DISCRIMINANT) != 1
                ):
                    raise ValueError("incomplete or duplicate switch slots")
            if r.slot == EvaluationSlot.FUNCTION_CREATION:
                self.function_child(r, EvaluationSlot.FUNCTION_PARAMETERS)
                self.function_child(r, EvaluationSlot.FUNCTION_BODY)

    def function_child(self, function, slot):
        children = self.function_children.get((function.unit, function.id, slot), ())
        if len(children) != 1:
            raise ValueError("incomplete or duplicate function slots")
        return children[0]

    def origin(self, unit, id):
        key = unit, id
        if key in self.origins:
            return self.origins[key]
        if key in self.active or len(self.active) >= 256:
            raise ValueError("cyclic or overdeep evaluation regions")
        self.active.add(key)
        r = self.get(self.regions, unit, id)
        parent = (
            self.get(self.regions, unit, r.parent) if r.parent is not None else None
        )
        inherited, complete = (
            self.origin(unit, r.parent) if parent is not None else (None, True)
        )
        if r.slot == EvaluationSlot.FUNCTION_CREATION:
            if r.split_parameters is None:
                raise ValueError("function must declare its parameter expression rule")
        elif r.split_parameters is not None:
            raise ValueError("unexpected parameter split rule")
        required = None
        if r.slot == EvaluationSlot.ROOT:
            if parent is not None or self.units[unit].root_region != r.id:
                raise ValueError("unqualified or nested root")
            required = EnvironmentKind.ROOT
        elif parent is None:
            raise ValueError("non-root without parent")
        elif r.slot in (
            EvaluationSlot.BLOCK,
            EvaluationSlot.CLASS,
            EvaluationSlot.FUNCTION_NAME,
            EvaluationSlot.CATCH,
            EvaluationSlot.CATCH_BODY,
        ):
            required = EnvironmentKind.BLOCK
        elif r.slot in (EvaluationSlot.SWITCH_CASE, EvaluationSlot.SWITCH_DISCRIMINANT):
            if parent.slot != EvaluationSlot.SWITCH:
                raise ValueError("switch slot has wrong owner")
            if r.slot == EvaluationSlot.SWITCH_CASE:
                required = EnvironmentKind.CASE
        elif r.slot in (
            EvaluationSlot.FUNCTION_PARAMETERS,
            EvaluationSlot.FUNCTION_BODY,
        ):
            if parent.slot != EvaluationSlot.FUNCTION_CREATION:
                raise ValueError("function slot has wrong owner")
            if r.slot == EvaluationSlot.FUNCTION_PARAMETERS:
                required = (
                    EnvironmentKind.PARAMETERS
                    if parent.split_parameters
                    else EnvironmentKind.FUNCTION_SHARED
                )
            else:
                parameters = self.function_child(
                    parent, EvaluationSlot.FUNCTION_PARAMETERS
                )
                inherited, params_complete = self.origin(unit, parameters.id)
                complete = complete and params_complete
                if parent.split_parameters:
                    required = EnvironmentKind.FUNCTION_VAR
        elif r.slot in (
            EvaluationSlot.PARAMETER_DEFAULT,
            EvaluationSlot.PARAMETER_COMPUTED,
        ):
            # Nested patterns keep this slot under the parameter region; the
            # producer computes ContainsExpression recursively, not simple-list.
            if parent.slot != EvaluationSlot.FUNCTION_PARAMETERS:
                raise ValueError("parameter expression has wrong owner")
            function = self.get(self.regions, unit, parent.parent)
            if not function.split_parameters:
                raise ValueError("parameter expression requires split environment")
        if required is not None:
            env = self.get(self.envs, unit, r.environment)
            if env.kind != required or env.owner != r.id or env.outer != inherited:
                raise ValueError(
                    "environment transition does not follow typed evaluation slot"
                )
            result = env.id, complete and r.complete
        else:
            if r.environment is not None:
                raise ValueError("transparent slot cannot supply an environment")
            result = inherited, complete and r.complete
        self.active.remove(key)
        self.origins[key] = result
        return result

    def canonical_inventory(self):
        return canonical_bindings(self.e.environments, self.e.occurrences)

    def run(self) -> CheckResult:
        self.source_units()
        self.topology()
        expected = self.canonical_inventory()
        if sorted(self.e.bindings, key=lambda b: b.id) != sorted(
            expected, key=lambda b: b.id
        ):
            raise ValueError("binding inventory does not match canonical occurrences")
        table = {(b.unit, b.environment, b.namespace, b.name): b for b in expected}
        for d in self.e.occurrences:
            self.span(d)
            env = self.get(self.envs, d.unit, d.environment)
            owner = self.get(self.regions, d.unit, env.owner)
            if env.kind == EnvironmentKind.FUNCTION_SHARED:
                owner = self.get(self.regions, d.unit, owner.parent)
            if not owner.start <= d.start < d.end <= owner.end:
                raise ValueError("declaration outside owning region")
        if self.refs.keys() != self.resolutions.keys():
            raise ValueError("resolution inventory is not total")
        computed = []
        for key, ref in sorted(self.refs.items()):
            self.span(ref)
            region = self.get(self.regions, ref.unit, ref.region)
            if not region.start <= ref.start < ref.end <= region.end:
                raise ValueError("reference outside evaluation region")
            if ref.namespace != Namespace.VALUE or not ref.name:
                raise ValueError(
                    "unsupported reference namespace or empty decoded name"
                )
            origin, complete = self.origin(ref.unit, ref.region)
            path, target = [], None
            state = ResolutionState.UNKNOWN
            cursor = origin
            if complete:
                state = ResolutionState.UNRESOLVED
                while cursor is not None:
                    path.append(cursor)
                    env = self.get(self.envs, ref.unit, cursor)
                    if not env.complete:
                        state = ResolutionState.UNKNOWN
                        break
                    binding = table.get((ref.unit, cursor, ref.namespace, ref.name))
                    if binding is not None:
                        target, state = binding.id, ResolutionState.RESOLVED
                        break
                    cursor = env.outer
            resolution = Resolution(
                ref.id, ref.unit, state, origin, target, tuple(path)
            )
            if resolution != self.resolutions[key]:
                raise ValueError(
                    "stored resolution differs from derived first-binding lookup"
                )
            computed.append(resolution)
        return CheckResult(tuple(computed))
