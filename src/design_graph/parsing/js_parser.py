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
from dataclasses import dataclass

from design_graph.core.constants import (
    JS_FUNCTION_FALLBACK_WINDOW,
    JS_FUNCTION_SCAN_LIMIT,
)
from design_graph.core.models import FunctionBoundary
from design_graph.core.patterns import RE_COMP_FN, RE_VISUAL_RETURN

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JavaScriptLexicalView:
    """Classify source positions so declarations inside text are not parsed as code."""

    source: str
    ignored_ranges: tuple[tuple[int, int], ...]

    @classmethod
    def analyze(cls, source: str) -> "JavaScriptLexicalView":
        ranges: list[tuple[int, int]] = []
        index = 0
        while index < len(source):
            char = source[index]
            following = source[index + 1] if index + 1 < len(source) else ""
            if char in {'"', "'", "`"}:
                end = cls._quoted_end(source, index, char)
                ranges.append((index, end))
                index = end
                continue
            if char == "/" and following == "/":
                end = source.find("\n", index + 2)
                end = len(source) if end < 0 else end
                ranges.append((index, end))
                index = end
                continue
            if char == "/" and following == "*":
                closing = source.find("*/", index + 2)
                end = len(source) if closing < 0 else closing + 2
                ranges.append((index, end))
                index = end
                continue
            index += 1
        return cls(source=source, ignored_ranges=tuple(ranges))

    @staticmethod
    def _quoted_end(source: str, opening: int, quote: str) -> int:
        escaped = False
        index = opening + 1
        while index < len(source):
            char = source[index]
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                return index + 1
            index += 1
        return len(source)

    def executable_matches(self, pattern: re.Pattern):
        range_index = 0
        for match in pattern.finditer(self.source):
            while (
                range_index < len(self.ignored_ranges)
                and self.ignored_ranges[range_index][1] <= match.start()
            ):
                range_index += 1
            if range_index < len(self.ignored_ranges):
                start, end = self.ignored_ranges[range_index]
                if start <= match.start() < end:
                    continue
            yield match


@dataclass(frozen=True)
class JavaScriptFunctionScanner:
    """Locate one function body without treating parameter objects as its body."""

    source: str

    def body_start(self, function_start: int) -> int | None:
        parameters_start = self.source.find("(", function_start)
        if parameters_start < 0 or parameters_start > function_start + 500:
            return None
        parameters_end = self._matching_delimiter(parameters_start, "(", ")")
        if parameters_end is None:
            return None
        index = parameters_end
        while index < len(self.source) and self.source[index].isspace():
            index += 1
        return index if index < len(self.source) and self.source[index] == "{" else None

    def function_end(self, function_start: int) -> int | None:
        body_start = self.body_start(function_start)
        if body_start is None:
            return None
        return self._matching_delimiter(body_start, "{", "}")

    def expression_end(self, expression_start: int) -> int:
        """Return the end of one return expression at its top-level semicolon."""
        depths = {"(": 0, "[": 0, "{": 0}
        pairs = {")": "(", "]": "[", "}": "{"}
        quote: str | None = None
        escaped = False
        line_comment = False
        block_comment = False
        limit = min(expression_start + JS_FUNCTION_SCAN_LIMIT, len(self.source))
        index = expression_start
        while index < limit:
            char = self.source[index]
            following = self.source[index + 1] if index + 1 < limit else ""
            if line_comment:
                line_comment = char not in "\r\n"
                index += 1
                continue
            if block_comment:
                if char == "*" and following == "/":
                    block_comment = False
                    index += 2
                else:
                    index += 1
                continue
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
                index += 1
                continue
            if char == "/" and following == "/":
                line_comment = True
                index += 2
                continue
            if char == "/" and following == "*":
                block_comment = True
                index += 2
                continue
            if char in {'"', "'", "`"}:
                quote = char
            elif char in depths:
                depths[char] += 1
            elif char in pairs:
                opening = pairs[char]
                if depths[opening] == 0 and char == "}":
                    return index
                depths[opening] = max(0, depths[opening] - 1)
            elif char == ";" and not any(depths.values()):
                return index
            index += 1
        return limit

    def _matching_delimiter(
        self,
        opening_index: int,
        opening: str,
        closing: str,
    ) -> int | None:
        depth = 0
        quote: str | None = None
        escaped = False
        line_comment = False
        block_comment = False
        limit = min(opening_index + JS_FUNCTION_SCAN_LIMIT, len(self.source))
        index = opening_index

        while index < limit:
            char = self.source[index]
            following = self.source[index + 1] if index + 1 < limit else ""

            if line_comment:
                line_comment = char not in "\r\n"
                index += 1
                continue
            if block_comment:
                if char == "*" and following == "/":
                    block_comment = False
                    index += 2
                else:
                    index += 1
                continue
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
                index += 1
                continue
            if char == "/" and following == "/":
                line_comment = True
                index += 2
                continue
            if char == "/" and following == "*":
                block_comment = True
                index += 2
                continue
            if char in {'"', "'", "`"}:
                quote = char
                index += 1
                continue
            if char == opening:
                depth += 1
            elif char == closing:
                depth -= 1
                if depth == 0:
                    return index + 1
            index += 1
        return None


def find_function_end(js: str, fn_start: int) -> int:
    """
    Scan forward from fn_start, counting '{' and '}', and return the index
    immediately after the matching closing brace.

    Falls back to fn_start + JS_FUNCTION_FALLBACK_WINDOW when:
    - No opening brace is found within 500 chars of fn_start
    - The scan reaches JS_FUNCTION_SCAN_LIMIT without finding the closing brace
    """
    function_end = JavaScriptFunctionScanner(js).function_end(fn_start)
    if function_end is None:
        logger.debug("find_function_end: no opening brace near %d — using fallback", fn_start)
        return min(fn_start + JS_FUNCTION_FALLBACK_WINDOW, len(js))
    return function_end


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

    visual_return = RE_VISUAL_RETURN.search(window)
    selected_return = visual_return or re.search(r"\breturn\s*\(", window)
    if selected_return is None:
        return ""
    expression_start = selected_return.start() + len("return")
    while expression_start < len(window) and window[expression_start].isspace():
        expression_start += 1
    scanner = JavaScriptFunctionScanner(window)
    if expression_start < len(window) and window[expression_start] == "(":
        expression_end = scanner._matching_delimiter(expression_start, "(", ")")
        if expression_end is not None:
            return window[expression_start + 1:expression_end - 1].strip()
    expression_end = scanner.expression_end(expression_start)
    return window[expression_start:expression_end].strip()


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
    scanner = JavaScriptFunctionScanner(js)

    lexical_view = JavaScriptLexicalView.analyze(js)
    for match in lexical_view.executable_matches(name_pattern):
        name = match.group(1)
        fn_start = match.start()
        fn_end = find_function_end(js, fn_start)

        body_start = scanner.body_start(fn_start)
        if body_start is None or body_start > fn_end:
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
