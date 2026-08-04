"""
JSX sanitization for AI-agent consumption.

sanitize_jsx() strips JavaScript control flow out of a component's return
block, replacing dynamic expressions with typed markers (core.models.JsxMarker)
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

from design_graph.core.models import JsxMarker, JsxMarkerKind
from design_graph.core.patterns import (
    RE_JSX_CONDITIONAL_HEAD,
    RE_JSX_EITHER_ELSE_BRANCH,
    RE_JSX_EITHER_HEAD,
    RE_JSX_LIST_HEAD,
    RE_JSX_MARKUP_CONDITIONAL_HEAD,
    RE_JSX_MARKUP_EITHER_HEAD,
    RE_LONG_ARROW_FN,
    RE_LONG_EVENT_HANDLER,
    RE_LONG_TERNARY,
    RE_STYLE_PROP,
)
from design_graph.parsing.js_parser import find_matching_delimiter

logger = logging.getLogger(__name__)

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
    jsx = RE_LONG_EVENT_HANDLER.sub("on[handler]", jsx)
    jsx = RE_LONG_ARROW_FN.sub(".[fn]", jsx)

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
        props = RE_STYLE_PROP.findall(inner)[:_STYLE_BLOCK_PREVIEW_PROP_COUNT]
        preview = ", ".join(f"{k}: {v.strip()}" for k, v in props)
        return f"style={{{{ {preview}, ... }}}}"
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
        pieces.append("{...}")
        cursor = match.end()
    pieces.append(jsx[cursor:])
    return "".join(pieces)
