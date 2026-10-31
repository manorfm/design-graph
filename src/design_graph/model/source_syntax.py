"""Closed per-unit syntax evidence and parser-free candidate projection.

This is consistency admission of trusted capture facts, not authentication of a
coherently rewritten AST. BindingCaptureIR/3 remains unchanged (syntax unknown).
The explicit source-syntax-capture/1 wrapper is NOT a persisted context format.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, fields, is_dataclass

from .binding_capture_ir import BindingCaptureIR, binding_id
from .binding_ir import _decode, _object, _validate_typed

MAX_CHARS = 16 * 1024 * 1024
MAX_NODES = 1_000_000
MAX_WORK = 1_000_000
MAX_DEPTH = 48
MAX_UNITS = 16
MAX_FACTS = 20_000
MAX_CANDIDATES = 1024


@dataclass(frozen=True)
class Span:
    start: int
    end: int


@dataclass(frozen=True)
class Token:
    name: str
    span: Span


@dataclass(frozen=True)
class PathWitness:
    span: Span
    root_reference: str
    root: Token
    keys: tuple[Token, ...]


@dataclass(frozen=True)
class MemberUse:
    id: str
    member_span: Span
    object_reference: str
    key: Token


@dataclass(frozen=True)
class AliasInitializer:
    id: str
    declaration: str
    binding: str
    declarator_span: Span
    initializer: PathWitness


@dataclass(frozen=True)
class PublicationMember:
    id: str
    property_span: Span
    kind: str
    computed: bool
    method: bool
    key: Token | None
    value_reference: str | None


def _unsupported_member(member):
    return (
        member.kind != "init"
        or member.computed
        or member.method
        or member.key is None
        or member.value_reference is None
        or member.key.name == "__proto__"
    )


@dataclass(frozen=True)
class Publication:
    id: str
    assignment_span: Span
    operator: str
    path: PathWitness
    object_span: Span
    members: tuple[PublicationMember, ...]


@dataclass(frozen=True)
class Unsupported:
    id: str
    kind: str
    span: Span


@dataclass(frozen=True)
class SourceSyntax:
    version: str
    unit: str
    uses: tuple[MemberUse, ...]
    aliases: tuple[AliasInitializer, ...]
    publications: tuple[Publication, ...]
    unsupported: tuple[Unsupported, ...]


def _finite(value):
    """Bound even typed caller objects before recursive type/semantic checks."""
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count > MAX_NODES or depth > MAX_DEPTH:
            raise ValueError("source syntax object/depth budget exceeded")
        if isinstance(item, str) and len(item) > MAX_CHARS:
            raise ValueError("source syntax string budget exceeded")
        if is_dataclass(item) and not isinstance(item, type):
            children = [getattr(item, f.name) for f in fields(item)]
        elif type(item) in (tuple, list):
            children = item
        elif type(item) is dict:
            children = tuple(item.values())
        else:
            children = ()
        if len(children) + len(pending) > MAX_NODES:
            raise ValueError("source syntax container budget exceeded")
        pending.extend((child, depth + 1) for child in children)


def _json_admit(text):
    if type(text) is not str or len(text) > MAX_CHARS:
        raise ValueError("source syntax transport budget exceeded")
    depth = count = 0
    quoted = escaped = False
    for ch in text:
        if quoted:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                quoted = False
        elif ch == '"':
            quoted = True
        elif ch in "[{":
            depth += 1
            count += 1
            if depth > MAX_DEPTH or count > MAX_NODES:
                raise ValueError("source syntax transport depth/record budget exceeded")
        elif ch in "]}":
            depth -= 1
            if depth < 0:
                raise ValueError("invalid source syntax nesting")
    if quoted or depth:
        raise ValueError("incomplete source syntax transport")


@dataclass(frozen=True)
class SourceSyntaxCapture:
    version: str
    producer_fingerprint: str
    lexical: BindingCaptureIR
    source_syntax: SourceSyntax

    def check(self):
        _finite(self)
        _validate_typed(SourceSyntaxCapture, self)
        if self.version != "source-syntax-capture/1" or not re.fullmatch(
            "[0-9a-f]{64}", self.producer_fingerprint
        ):
            raise ValueError("unsupported source syntax capture contract/custody")
        self.lexical.check()
        _SyntaxChecker(self).run()

    def to_json(self):
        self.check()
        text = json.dumps(
            asdict(self),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        _json_admit(text)
        return text

    @classmethod
    def from_json(cls, text):
        _json_admit(text)
        value = _decode(cls, json.loads(text, object_pairs_hook=_object))
        value.check()
        return value


def syntax_status(capture):
    """Legacy captures never acquire syntax facts by a version/field default."""
    if type(capture) is BindingCaptureIR:
        capture.check()
        return "unknown"
    capture.check()
    return "captured"


class _SyntaxChecker:
    def __init__(self, capture):
        self.c = capture
        self.s = capture.source_syntax
        self.ir = capture.lexical.ir
        self.unit = self.ir.units[0]
        self.body = self.unit.source.encode("utf8")
        self.refs = {r.id: r for r in self.ir.references}
        self.decls = {d.id: d for d in self.ir.occurrences}
        self.bindings = {b.id: b for b in self.ir.bindings}
        self.bounds = {0}
        offset = 0
        for char in self.unit.source:
            offset += len(char.encode("utf8"))
            self.bounds.add(offset)

    def span(self, span, parent=None):
        if not (
            span.start in self.bounds
            and span.end in self.bounds
            and 0 <= span.start < span.end <= len(self.body)
        ):
            raise ValueError("invalid UTF8 source span")
        if parent and not (parent.start <= span.start < span.end <= parent.end):
            raise ValueError("detached source span")

    def token(self, token, parent):
        self.span(token.span, parent)
        spelling = self.body[token.span.start : token.span.end].decode("utf8")

        # Only identifier escape decoding, not a JavaScript reader/parser.
        def escape(match):
            code = int(match[1] or match[2], 16)
            if code > 0x10FFFF or 0xD800 <= code <= 0xDFFF:
                raise ValueError("invalid identifier escape")
            return chr(code)

        decoded = re.sub(
            r"\\u(?:\{([0-9a-fA-F]{1,6})\}|([0-9a-fA-F]{4}))", escape, spelling
        )
        if not token.name or decoded != token.name or "\\" in decoded:
            raise ValueError("changed source key anchor")

    def reference(self, id_, parent):
        ref = self.refs.get(id_)
        if ref is None or ref.unit != self.unit.id:
            raise ValueError("foreign native reference")
        self.span(Span(ref.start, ref.end), parent)
        return ref

    def path(self, path, parent):
        self.span(path.span, parent)
        root = self.reference(path.root_reference, path.span)
        self.token(path.root, path.span)
        if (
            path.root.name != root.name
            or path.root.span != Span(root.start, root.end)
            or path.span.start != root.start
            or not 1 <= len(path.keys) <= 64
        ):
            raise ValueError("invalid native path root")
        end = root.end
        for key in path.keys:
            self.token(key, path.span)
            if key.span.start <= end or not re.fullmatch(
                rb"\s*\.\s*", self.body[end : key.span.start]
            ):
                raise ValueError("non-static path witness")
            end = key.span.end
        if end != path.span.end:
            raise ValueError("detached path end")

    def run(self):
        s = self.s
        if s.version != "source-syntax/1" or s.unit != self.unit.id:
            raise ValueError("unsupported or foreign per-unit syntax")
        groups = (
            (s.uses, "u"),
            (s.aliases, "a"),
            (s.publications, "p"),
            (s.unsupported, "x"),
        )
        if (
            sum(len(rows) for rows, _ in groups)
            + sum(len(p.members) for p in s.publications)
            > MAX_FACTS
        ):
            raise ValueError("source syntax fact budget exceeded")
        for rows, prefix in groups:
            if any(row.id != prefix + str(i) for i, row in enumerate(rows)):
                raise ValueError("duplicate or noncanonical syntax ID")
        for use in s.uses:
            self.span(use.member_span)
            ref = self.reference(use.object_reference, use.member_span)
            self.token(use.key, use.member_span)
            if (
                use.member_span.start != ref.start
                or use.member_span.end != use.key.span.end
                or not re.fullmatch(
                    rb"\s*\.\s*", self.body[ref.end : use.key.span.start]
                )
            ):
                raise ValueError("invalid member-use node witness")
        for alias in s.aliases:
            self.span(alias.declarator_span)
            self.path(alias.initializer, alias.declarator_span)
            declaration = self.decls.get(alias.declaration)
            binding = self.bindings.get(alias.binding)
            if (
                declaration is None
                or binding is None
                or alias.declaration not in binding.occurrences
                or alias.binding
                != binding_id(self.unit.id, declaration.environment, declaration.name)
            ):
                raise ValueError("invalid alias native declaration/binding")
            self.span(Span(declaration.start, declaration.end), alias.declarator_span)
            if (
                declaration.start != alias.declarator_span.start
                or alias.initializer.span.end != alias.declarator_span.end
                or not re.fullmatch(
                    rb"\s*=\s*",
                    self.body[declaration.end : alias.initializer.span.start],
                )
            ):
                raise ValueError("invalid alias initializer node witness")
        for pub in s.publications:
            self.publication(pub)
        allowed = {
            "computed-or-optional-member",
            "unsupported-publication-member",
            "unsupported-publication-path",
        }
        for fact in s.unsupported:
            self.span(fact.span)
            if fact.kind not in allowed:
                raise ValueError("unknown unsupported alternative")

    def publication(self, pub):
        self.span(pub.assignment_span)
        self.path(pub.path, pub.assignment_span)
        self.span(pub.object_span, pub.assignment_span)
        if (
            pub.operator != "="
            or pub.assignment_span.start != pub.path.span.start
            or pub.assignment_span.end != pub.object_span.end
            or not re.fullmatch(
                rb"\s*=\s*", self.body[pub.path.span.end : pub.object_span.start]
            )
            or self.body[pub.object_span.start : pub.object_span.start + 1] != b"{"
            or self.body[pub.object_span.end - 1 : pub.object_span.end] != b"}"
        ):
            raise ValueError("invalid publication node witness")
        previous = pub.object_span.start
        for i, member in enumerate(pub.members):
            self.span(member.property_span, pub.object_span)
            if (
                member.id != pub.id + "m" + str(i)
                or member.property_span.start <= previous
                or member.kind not in ("init", "get", "set", "spread")
            ):
                raise ValueError("invalid publication member identity/kind")
            previous = member.property_span.end
            if member.key:
                self.token(member.key, member.property_span)
                if member.computed:
                    raise ValueError("computed member cannot claim a static key")
            if member.value_reference:
                self.reference(member.value_reference, member.property_span)
            unsafe = _unsupported_member(member)
            if not unsafe:
                ref = self.refs[member.value_reference]
                key = member.key.span
                shorthand = key == Span(ref.start, ref.end)
                if (
                    key.start != member.property_span.start
                    or ref.end != member.property_span.end
                    or (
                        not shorthand
                        and not re.fullmatch(
                            rb"\s*:\s*", self.body[key.end : ref.start]
                        )
                    )
                ):
                    raise ValueError("invalid publication property key/value witness")
            marked = any(
                x.kind == "unsupported-publication-member"
                and x.span == member.property_span
                for x in self.s.unsupported
            )
            if unsafe != marked:
                raise ValueError("removed or reinterpreted unsupported alternative")


@dataclass(frozen=True)
class SourceInventory:
    snapshot: str
    input_artifact: str
    units: tuple[str, ...]


@dataclass(frozen=True)
class Candidate:
    alias_unit: str
    alias: str
    alias_binding: str
    declaration: str
    provider_unit: str
    publication: str
    member: str
    value_reference: str
    binding: str
    occurrences: tuple[str, ...]
    evidence_spans: tuple[Span, ...]


@dataclass(frozen=True)
class CandidateSelection:
    scope: SourceInventory
    unit: str
    use: str
    status: str
    candidates: tuple[Candidate, ...]
    rationale: tuple[str, ...]
    unresolved_alternatives: tuple[str, ...]
    runtime_claim: bool


def project_candidates(scope, captures, unit, use_id):
    """Always re-admit; no caller supplied checked flag, cache or runtime edge."""
    _finite((scope, captures))
    _validate_typed(SourceInventory, scope)
    if type(captures) is not tuple or not 0 < len(captures) <= MAX_UNITS:
        raise ValueError("finite immutable source inventory required")
    if (
        not scope.snapshot
        or not scope.input_artifact
        or len(scope.units) != len(set(scope.units))
    ):
        raise ValueError("explicit snapshot/input inventory required")
    for capture in captures:
        if type(capture) is not SourceSyntaxCapture:
            raise ValueError("legacy syntax is unknown; explicit recapture required")
        capture.check()
    by_unit = {c.source_syntax.unit: c for c in captures}
    if (
        len(by_unit) != len(captures)
        or set(by_unit) != set(scope.units)
        or unit not in by_unit
    ):
        raise ValueError("foreign or incomplete source inventory scope")
    consumer = by_unit[unit]
    use = next((u for u in consumer.source_syntax.uses if u.id == use_id), None)
    if use is None:
        raise ValueError("unknown qualified member-use ID")
    resolutions = {r.id: r for r in consumer.lexical.ir.resolutions}
    object_target = resolutions[use.object_reference].target
    risks = {
        "host-root-unknown",
        "global-writes-unknown",
        "execution-order-unknown",
        "unknown-scripts",
    }
    candidates = []
    aliases = tuple(
        a for a in consumer.source_syntax.aliases if a.binding == object_target
    )
    work = len(aliases) * (
        len(consumer.lexical.ir.references)
        + sum(
            len(c.lexical.ir.resolutions)
            + len(c.lexical.ir.bindings)
            + len(c.source_syntax.publications)
            + sum(len(p.members) for p in c.source_syntax.publications)
            for c in captures
        )
    )
    if work > MAX_WORK:
        raise ValueError("source candidate work budget exceeded")
    for alias in aliases:
        if resolutions[alias.initializer.root_reference].state.value != "unresolved":
            continue
        _alias_risks(consumer, alias, resolutions, risks)
        for provider in sorted(captures, key=lambda c: c.source_syntax.unit):
            for candidate in _provider_candidates(provider, alias, use, unit, risks):
                candidates.append(candidate)
                if len(candidates) > MAX_CANDIDATES:
                    raise ValueError("source candidate budget exceeded")
    if len(candidates) > 1:
        risks.add("duplicate-publication-candidates")
    return CandidateSelection(
        scope,
        unit,
        use_id,
        "source-candidate"
        if len(candidates) == 1
        else "ambiguous"
        if candidates
        else "unresolved",
        tuple(candidates),
        ("native lexical alias and value identities; explicit source path only",),
        tuple(sorted(risks)),
        False,
    )


def _alias_risks(consumer, alias, resolutions, risks):
    declaration = next(
        d for d in consumer.lexical.ir.occurrences if d.id == alias.declaration
    )
    if declaration.kind.value != "const":
        risks.add("alias-mutable-or-reassigned")
    for ref in consumer.lexical.ir.references:
        if resolutions[ref.id].target != alias.binding:
            continue
        if alias.declarator_span.start <= ref.start < alias.declarator_span.end:
            continue
        if ref.access.value in ("write", "read-write"):
            risks.add("alias-mutable-or-reassigned")


def _signature(path):
    return path.root.name, tuple(k.name for k in path.keys)


def _publication_target(pub, use, targets, bindings, risks):
    if any(_unsupported_member(m) for m in pub.members):
        risks.add("unsupported-publication-object")
        return None
    matches = [m for m in pub.members if m.key.name == use.key.name]
    if len(matches) != 1:
        risks.add("missing-or-duplicate-property")
        return None
    member = matches[0]
    resolution = targets[member.value_reference]
    if resolution.state.value != "resolved" or resolution.target not in bindings:
        risks.add("unresolved-publication-value")
        return None
    return member, bindings[resolution.target]


def _provider_candidates(provider, alias, use, unit, risks):
    targets = {r.id: r for r in provider.lexical.ir.resolutions}
    bindings = {b.id: b for b in provider.lexical.ir.bindings}
    for pub in provider.source_syntax.publications:
        if _signature(alias.initializer) != _signature(pub.path):
            continue
        if targets[pub.path.root_reference].state.value != "unresolved":
            continue
        selected = _publication_target(pub, use, targets, bindings, risks)
        if selected is None:
            continue
        member, target = selected
        yield Candidate(
            unit,
            alias.id,
            alias.binding,
            alias.declaration,
            provider.source_syntax.unit,
            pub.id,
            member.id,
            member.value_reference,
            target.id,
            target.occurrences,
            (
                use.member_span,
                alias.declarator_span,
                alias.initializer.span,
                pub.assignment_span,
                pub.object_span,
                member.property_span,
            ),
        )
