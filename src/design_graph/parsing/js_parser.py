"""
JavaScript function boundary detection and JSX return-block extraction.

Key design decisions:
- find_function_end uses brace counting (not regex) for correctness with
  nested objects, template literals, and JSX double-braces {{...}}.
- All functions are pure and thread-safe (read-only on the JS string).
- FunctionBoundary.end guarantees no overlap between sibling functions,
  which is the property that makes parallel extraction safe.
"""

from __future__ import annotations

import logging
import re

from design_graph.core.constants import (
    JS_FUNCTION_FALLBACK_WINDOW,
    JS_FUNCTION_SCAN_LIMIT,
)
from design_graph.core.models import FunctionBoundary
from design_graph.core.patterns import RE_COMP_FN

logger = logging.getLogger(__name__)


def find_function_end(js: str, fn_start: int) -> int:
    """
    Scan forward from fn_start, counting '{' and '}', and return the index
    immediately after the matching closing brace.

    Falls back to fn_start + JS_FUNCTION_FALLBACK_WINDOW when:
    - No opening brace is found within 500 chars of fn_start
    - The scan reaches JS_FUNCTION_SCAN_LIMIT without finding the closing brace
    """
    first_brace = js.find("{", fn_start)

    if first_brace < 0 or first_brace > fn_start + 500:
        logger.debug("find_function_end: no opening brace near %d — using fallback", fn_start)
        return min(fn_start + JS_FUNCTION_FALLBACK_WINDOW, len(js))

    depth = 0
    limit = min(fn_start + JS_FUNCTION_SCAN_LIMIT, len(js))
    i = first_brace

    while i < limit:
        ch = js[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1

    logger.debug(
        "find_function_end: reached limit at %d without closing brace (fn_start=%d)",
        limit, fn_start,
    )
    return limit


def extract_return_block(js: str, fn_start: int, fn_end: int) -> str:
    """
    Within the function body [fn_start, fn_end], locate the return statement
    and extract the content between the outer parentheses.

    Handles both 'return (' and 'return(' forms.
    Returns an empty string when no return statement is found.
    """
    if not js or fn_start >= fn_end:
        return ""

    window = js[fn_start:fn_end]

    # Find the return keyword with its opening paren
    ret_idx = -1
    for marker in ("return (", "return("):
        idx = window.find(marker)
        if idx >= 0:
            ret_idx = idx
            break

    if ret_idx < 0:
        return ""

    paren_start = window.find("(", ret_idx)
    if paren_start < 0:
        return ""

    depth = 0
    i = paren_start

    while i < len(window):
        ch = window[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return window[paren_start + 1 : i].strip()
        i += 1

    # Fallback: return everything after the opening paren
    return window[paren_start + 1 :].strip()


def find_function_boundaries(
    js: str, name_pattern: re.Pattern
) -> list[FunctionBoundary]:
    """
    Find all functions whose names match name_pattern and return their
    precise character boundaries.

    The returned list is sorted by start position. Boundaries are guaranteed
    not to overlap: boundary[i].end <= boundary[i+1].start.
    """
    boundaries: list[FunctionBoundary] = []

    for match in name_pattern.finditer(js):
        name = match.group(1)
        fn_start = match.start()
        fn_end = find_function_end(js, fn_start)

        # body_start = first "{" after the function keyword
        body_start = js.find("{", fn_start)
        if body_start < 0 or body_start > fn_end:
            body_start = fn_start

        boundaries.append(FunctionBoundary(
            name=name,
            start=fn_start,
            body_start=body_start,
            end=fn_end,
        ))

    boundaries.sort(key=lambda b: b.start)

    # Enforce non-overlap: clip each boundary's end to the start of the next
    for i in range(len(boundaries) - 1):
        if boundaries[i].end > boundaries[i + 1].start:
            logger.debug(
                "js_parser: clipping %s.end from %d to %d (overlapped %s.start)",
                boundaries[i].name, boundaries[i].end,
                boundaries[i + 1].start, boundaries[i + 1].name,
            )
            boundaries[i] = FunctionBoundary(
                name=boundaries[i].name,
                start=boundaries[i].start,
                body_start=boundaries[i].body_start,
                end=boundaries[i + 1].start,
            )

    return boundaries


def find_all_boundaries(js: str) -> list[FunctionBoundary]:
    """
    Find boundaries for all PascalCase functions in the JS string.
    Used as the entry point for the extraction pipeline.
    """
    return find_function_boundaries(js, RE_COMP_FN)
