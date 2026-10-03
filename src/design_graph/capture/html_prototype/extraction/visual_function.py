"""Value object for deciding whether a JavaScript function renders UI."""

from __future__ import annotations

from dataclasses import dataclass

from design_graph.capture.html_prototype.sources import FunctionBoundary
from design_graph.capture.html_prototype.patterns import RE_VISUAL_RETURN


@dataclass(frozen=True)
class VisualFunctionCandidate:
    boundary: FunctionBoundary
    body: str

    @classmethod
    def from_source(cls, source: str, boundary: FunctionBoundary) -> "VisualFunctionCandidate":
        return cls(boundary=boundary, body=source[boundary.start:boundary.end])

    @property
    def renders_visual_output(self) -> bool:
        return bool(RE_VISUAL_RETURN.search(self.body))

