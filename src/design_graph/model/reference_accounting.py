"""Format-neutral reference accounting; no parser, capture or runtime dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReferenceAccounting:
    """Validate scope/target integrity before making local absence claims.

    A parsed tree is not a coverage certificate. Gaps retain their own regions;
    a positive lexical fact and value availability are independent properties.
    """

    byte_length: int
    grammar: str
    scopes: tuple[dict[str, Any], ...]
    declarations: tuple[dict[str, Any], ...]
    references: tuple[dict[str, Any], ...]
    gaps: tuple[dict[str, Any], ...]
    publications: tuple[dict[str, Any], ...] = ()
    regions: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_capture(cls, payload: dict[str, Any]) -> ReferenceAccounting:
        result = cls(
            payload["bytes"],
            payload["grammar"],
            tuple(payload["scopes"]),
            tuple(payload["declarations"]),
            tuple(payload["references"]),
            tuple(payload["gaps"]),
            tuple(payload.get("publications", ())),
            tuple(payload.get("regions", ())),
        )
        result.validate()
        return result

    def validate(self) -> None:
        if self.byte_length < 0 or not self.grammar:
            raise ValueError("invalid reference accounting origin")
        scopes = {s["id"]: s for s in self.scopes}
        declarations = {d["id"]: d for d in self.declarations}
        if len(scopes) != len(self.scopes) or len(declarations) != len(
            self.declarations
        ):
            raise ValueError("duplicate scope or declaration identity")
        for row in (*self.scopes, *self.declarations, *self.references, *self.gaps):
            start, end = row["span"]
            if not 0 <= start <= end <= self.byte_length:
                raise ValueError("reference span outside unit")
        self._validate_ancestry(scopes)
        for declaration in self.declarations:
            if declaration["scope"] not in scopes:
                raise ValueError("declaration without lexical scope")
        for reference in self.references:
            self._validate_reference(reference, scopes, declarations)

    def _validate_ancestry(self, scopes: dict[Any, dict[str, Any]]) -> None:
        for scope in self.scopes:
            seen = {scope["id"]}
            parent = scope["parent"]
            while parent is not None:
                if parent not in scopes or parent in seen:
                    raise ValueError("invalid lexical ancestry")
                seen.add(parent)
                parent = scopes[parent]["parent"]

    def _validate_reference(self, reference, scopes, declarations) -> None:
        if reference["scope"] not in scopes:
            raise ValueError("reference without lexical scope")
        # Only the scope covering the occurrence can resolve it. Containment, not
        # innermost: a switch discriminant lies in the switch block's span yet is
        # read from the enclosing scope.
        scope_start, scope_end = scopes[reference["scope"]]["span"]
        start, end = reference["span"]
        if not scope_start <= start <= end <= scope_end:
            raise ValueError("reference outside its lexical scope")
        target = reference["target"]
        if (reference["status"] == "proved") != (target is not None):
            raise ValueError("proof and target disagree")
        if target is None:
            return
        if target not in declarations:
            raise ValueError("dangling declaration target")
        ancestry = []
        current = reference["scope"]
        while current is not None:
            ancestry.append(current)
            current = scopes[current]["parent"]
        if declarations[target]["scope"] not in ancestry:
            raise ValueError("target outside lexical ancestry")
        if self._nearest_bindings(reference["name"], ancestry) != [target]:
            raise ValueError("target is not the nearest unique binding")

    def _nearest_bindings(self, name: str, ancestry: list[Any]) -> list[Any]:
        """Resolve the name before comparing identities; no binding is not proof."""
        for scope in ancestry:
            candidates = [
                d["id"]
                for d in self.declarations
                if d["scope"] == scope and d["name"] == name
            ]
            if candidates:
                return candidates
        return []

    @property
    def complete(self) -> bool:
        return bool(self.scopes) and not self.gaps

    def external_read_names(self) -> frozenset[str]:
        """Unbound reads eligible for legacy literal lookup, never global binding proof."""
        return frozenset(
            r["name"]
            for r in self.references
            if r["status"] == "unresolved" and r["role"] in ("read", "component-type")
        )

    def coverage(self) -> dict[str, Any]:
        return {
            "state": "supported" if self.complete else "unknown",
            "grammar": self.grammar,
            "span_utf8": [0, self.byte_length],
            "gaps": list(self.gaps),
            "whole_document": "unknown",
            "absence_proved": self.complete and not self.external_read_names(),
        }
