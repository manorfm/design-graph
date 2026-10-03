"""
Intermediate shapes the html_prototype capture works with before producing
domain entities: the decomposed document, JS function boundaries and the
repeating DOM patterns of plain HTML.
"""

from __future__ import annotations

from dataclasses import dataclass

from design_graph.model.entities import StrEnum


@dataclass(frozen=True)
class RawSources:
    """Output of source_loader.decompose() — immutable view of the HTML file's content."""

    js: str
    css: str
    inner_html: str
    html_hash: str
    format: SourceFormat
    skipped_entries: int = 0  # bundle entries that failed base64/gzip decode (bundled_react only)


@dataclass(frozen=True)
class FunctionBoundary:
    """
    Exact character-level position of a JavaScript function in the JS string.

    start      — index of "function Name("
    body_start — index of the first "{" (function body open)
    end        — index after the matching "}" (function body close)

    Guarantee: for sibling functions, boundary[i].end <= boundary[i+1].start.
    This property is what makes parallel extraction safe.
    """

    name: str
    start: int
    body_start: int
    end: int


class SourceFormat(StrEnum):
    BUNDLED_REACT = "bundled_react"
    TAILWIND = "tailwind"
    PLAIN_HTML = "plain_html"


class SemanticType(StrEnum):
    """DOM-level semantic category from html_parser._infer_semantic_type —
    distinct value space from ComponentType (e.g. "nav" vs "navigation");
    _SEMANTIC_TYPE_TO_COMP_TYPE maps one to the other."""

    NAV = "nav"
    HEADER = "header"
    FOOTER = "footer"
    CARD = "card"
    MODAL = "modal"
    BADGE = "badge"
    FORM = "form"
    TABLE = "table"
    LIST_ITEM = "list-item"
    COMPONENT = "component"


@dataclass(frozen=True)
class DOMPattern:
    """A DOM structure that repeats >= N times — candidate for a component."""

    signature: str       # e.g. "div.card>img,h3,p,button"
    count: int
    first_example: str   # truncated HTML of the first occurrence
    inferred_name: str   # e.g. "RestaurantCard"
    semantic_type: SemanticType
