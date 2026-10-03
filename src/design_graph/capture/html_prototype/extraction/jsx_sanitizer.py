"""
JSX sanitization for AI-agent consumption.

sanitize_jsx() strips JavaScript control flow out of a component's return
block, replacing dynamic expressions with typed markers (JsxMarker)
that name which component renders there without exposing the logic around it.

Every collapse here locates the *true* end of a `{...}` JSX expression with
parsing.js_parser.find_matching_delimiter — a balanced-brace scan — instead
of a regex tail. A tail like `[^}]{0,400}\\}` stops at the FIRST `}` it
meets, and a component prop as ordinary as `color={C.red}` supplies one well
before the expression's real end. Balanced scanning has no such failure mode,
regardless of how many braces a prop nests.
"""

from __future__ import annotations

import logging
import re

from dataclasses import dataclass

from design_graph.model.entities import StrEnum
from design_graph.capture.html_prototype.patterns import (
    RE_JSX_CONDITIONAL_HEAD,
    RE_JSX_EITHER_ELSE_BRANCH,
    RE_JSX_EITHER_HEAD,
    RE_JSX_LIST_HEAD,
    RE_JSX_MARKUP_CONDITIONAL_HEAD,
    RE_JSX_MARKUP_EITHER_HEAD,
    RE_LONG_ARROW_FN,
    RE_LONG_EVENT_HANDLER,
    RE_LONG_TERNARY,
    RE_STYLE_PROP_PREVIEW,
)
from design_graph.capture.html_prototype.parsing.js_parser import find_matching_delimiter

logger = logging.getLogger(__name__)


class JsxMarkerKind(StrEnum):
    """The three ways sanitize_jsx collapses a dynamic JSX expression."""

    LIST = "list"
    CONDITIONAL = "conditional"
    EITHER = "either"


@dataclass(frozen=True)
class JsxMarker:
    """
    A typed placeholder standing in for one dynamic JSX expression — a
    `.map()` render, a `&&` short-circuit, or a `? :` ternary — so an AI
    agent can see which component renders there without the surrounding
    JS logic.

    LIST and CONDITIONAL name exactly one component; EITHER names two, in
    source order (then-branch, else-branch — e.g. `error ? <A/> : <B/>`
    becomes `("A", "B")`). The count is validated on construction so a
    caller can never assemble a marker that doesn't match its own kind.
    """

    kind: JsxMarkerKind
    component_names: tuple[str, ...]

    def __post_init__(self) -> None:
        expected = 2 if self.kind is JsxMarkerKind.EITHER else 1
        if len(self.component_names) != expected:
            raise ValueError(
                f"{self.kind} marker takes {expected} component name(s), "
                f"got {self.component_names!r}"
            )

    def __str__(self) -> str:
        return f"{{[{self.kind}:{'|'.join(self.component_names)}]}}"


# Literal markers sanitize_jsx (extraction/jsx_sanitizer.py) leaves behind
# for a collapsed region that isn't a named-component reference — JsxMarker
# above covers list/conditional/either, which always name one or two
# components. Defined once here so a marker's written form and its
# detection in was_simplified can never drift apart.
JSX_HANDLER_MARKER               = "={[handler]}"
JSX_ARROW_FN_MARKER              = ".[fn]"
JSX_STYLE_BLOCK_COLLAPSE_SUFFIX  = ", ... }}"
JSX_BARE_EXPRESSION_MARKER       = "{...}"

_SIMPLIFICATION_MARKERS: tuple[str, ...] = (
    JSX_HANDLER_MARKER,
    JSX_ARROW_FN_MARKER,
    JSX_STYLE_BLOCK_COLLAPSE_SUFFIX,
    JSX_BARE_EXPRESSION_MARKER,
    *(f"{{[{kind}:" for kind in JsxMarkerKind),
)


def was_simplified(jsx: str) -> bool:
    """
    True when sanitize_jsx left at least one collapse marker in this JSX —
    the stored source is then a simplification, not the original text.
    """
    return any(marker in jsx for marker in _SIMPLIFICATION_MARKERS)

_STYLE_BLOCK_COLLAPSE_THRESHOLD = 400
_STYLE_BLOCK_PREVIEW_PROP_COUNT = 6

_MARKED_REGION_PATTERNS: tuple[tuple[re.Pattern, JsxMarkerKind], ...] = (
    (RE_JSX_LIST_HEAD, JsxMarkerKind.LIST),
    (RE_JSX_CONDITIONAL_HEAD, JsxMarkerKind.CONDITIONAL),
    (RE_JSX_EITHER_HEAD, JsxMarkerKind.EITHER),
)

_MARKUP_GUARD_PATTERNS: tuple[re.Pattern, ...] = (
    RE_JSX_MARKUP_CONDITIONAL_HEAD,
    RE_JSX_MARKUP_EITHER_HEAD,
)


def sanitize_jsx(jsx: str) -> str:
    """
    Strip JavaScript logic from JSX, replacing dynamic expressions with
    typed markers that preserve structural information for AI agents:

      {[list:ComponentName]}           — .map() list rendering
      {[conditional:ComponentName]}    — short-circuit && rendering
      {[either:ComponentA|ComponentB]} — ternary between components

    Static content, tags, inline styles, and component names are preserved.
    A conditional/ternary wrapping raw markup instead of a named component
    (an icon's <svg>, a decorative <span>) is never collapsed — see
    _protected_markup_spans — since that markup is the only copy of its own
    visual detail, unlike a component whose real shape is one
    get_component_spec call away.
    """
    jsx = RE_LONG_EVENT_HANDLER.sub(rf"\1{JSX_HANDLER_MARKER}", jsx)
    jsx = RE_LONG_ARROW_FN.sub(JSX_ARROW_FN_MARKER, jsx)

    marker_counts: dict[JsxMarkerKind, int] = {}
    for head, kind in _MARKED_REGION_PATTERNS:
        jsx, marker_counts[kind] = _collapse_marked_regions(jsx, head, kind)

    jsx = _collapse_long_style_blocks(jsx)
    jsx = _collapse_long_expressions(jsx, _protected_markup_spans(jsx))

    jsx = re.sub(r"\n{3,}", "\n\n", jsx)

    if any(marker_counts.values()):
        logger.debug(
            "sanitize_jsx: inserted %d list, %d conditional, %d either markers",
            marker_counts[JsxMarkerKind.LIST],
            marker_counts[JsxMarkerKind.CONDITIONAL],
            marker_counts[JsxMarkerKind.EITHER],
        )

    return jsx.strip()


def _collapse_marked_regions(jsx: str, head: re.Pattern, kind: JsxMarkerKind) -> tuple[str, int]:
    """
    Replace every `{...}` JSX expression matching `head` with its JsxMarker.

    `head` matches only up to the opening `<Component` tag; the expression's
    true end is found by scanning forward from the leading `{` for its
    balanced closing `}`, so a component prop with its own `{}` can never
    cut the match short.
    """
    pieces: list[str] = []
    cursor = 0
    count = 0
    for match in head.finditer(jsx):
        if match.start() < cursor:
            continue  # nested inside a region this same pass already collapsed
        region_end = find_matching_delimiter(jsx, match.start(), "{", "}")
        if region_end is None:
            continue  # unbalanced — leave the raw text untouched rather than guess

        names = (match.group(1),)
        if kind is JsxMarkerKind.EITHER:
            else_branch = RE_JSX_EITHER_ELSE_BRANCH.search(jsx[match.start():region_end])
            if else_branch is None:
                continue  # else branch has no component (e.g. `: null`) — not ours to collapse
            names = (names[0], else_branch.group(1))

        pieces.append(jsx[cursor:match.start()])
        pieces.append(str(JsxMarker(kind, names)))
        cursor = region_end
        count += 1

    pieces.append(jsx[cursor:])
    return "".join(pieces), count


def _protected_markup_spans(jsx: str) -> list[tuple[int, int]]:
    """
    Balanced spans of raw-markup conditionals/ternaries that must survive
    _collapse_long_expressions regardless of length. Computed against the
    jsx string as it stands right before that call, so its offsets line up.
    """
    spans: list[tuple[int, int]] = []
    for head in _MARKUP_GUARD_PATTERNS:
        for match in head.finditer(jsx):
            region_end = find_matching_delimiter(jsx, match.start(), "{", "}")
            if region_end is not None:
                spans.append((match.start(), region_end))
    return spans


def _collapse_long_style_blocks(jsx: str) -> str:
    def _collapse(match: re.Match) -> str:
        inner = match.group(0)
        if len(inner) <= _STYLE_BLOCK_COLLAPSE_THRESHOLD:
            return inner
        props = RE_STYLE_PROP_PREVIEW.findall(inner)[:_STYLE_BLOCK_PREVIEW_PROP_COUNT]
        preview = ", ".join(f"{k}: {v.strip()}" for k, v in props)
        return f"style={{{{ {preview}{JSX_STYLE_BLOCK_COLLAPSE_SUFFIX}"
    return re.sub(r"style=\{\{[^}]{200,}\}\}", _collapse, jsx)


def _collapse_long_expressions(jsx: str, protected: list[tuple[int, int]]) -> str:
    """Fallback: bare `{...}` for any remaining expression over 300 chars,
    except spans _protected_markup_spans identified as raw-markup regions."""
    pieces: list[str] = []
    cursor = 0
    for match in RE_LONG_TERNARY.finditer(jsx):
        if match.start() < cursor:
            continue
        if any(start <= match.start() and match.end() <= end for start, end in protected):
            continue
        pieces.append(jsx[cursor:match.start()])
        pieces.append(JSX_BARE_EXPRESSION_MARKER)
        cursor = match.end()
    pieces.append(jsx[cursor:])
    return "".join(pieces)
