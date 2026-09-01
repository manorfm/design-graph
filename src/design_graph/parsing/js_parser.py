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
from collections.abc import Iterator
from dataclasses import dataclass

from design_graph.core.constants import (
    JS_FUNCTION_FALLBACK_WINDOW,
    JS_FUNCTION_SCAN_LIMIT,
)
from design_graph.core.models import FunctionBoundary
from design_graph.core.patterns import RE_COMP_ARROW_FN, RE_COMP_FN, RE_VISUAL_RETURN

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
        """
        Locate the start of a function's body — the '{' of a block body, or the
        '(' of an arrow function's implicit-return parenthesized expression
        (const Name = (...) => ( <jsx/> )). Skips over an intervening '=>' so
        arrow-function declarations resolve the same way as `function Name(...)`.
        """
        parameters_start = self.source.find("(", function_start)
        if parameters_start < 0 or parameters_start > function_start + 500:
            return None
        parameters_end = self._matching_delimiter(parameters_start, "(", ")")
        if parameters_end is None:
            return None
        index = parameters_end
        while index < len(self.source) and self.source[index].isspace():
            index += 1
        if self.source[index:index + 2] == "=>":
            index += 2
            while index < len(self.source) and self.source[index].isspace():
                index += 1
        return index if index < len(self.source) and self.source[index] in "{(" else None

    def function_end(self, function_start: int) -> int | None:
        body_start = self.body_start(function_start)
        if body_start is None:
            return None
        opening = self.source[body_start]
        closing = "}" if opening == "{" else ")"
        return self._matching_delimiter(body_start, opening, closing)

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


def find_matching_delimiter(
    js: str, opening_index: int, opening: str = "{", closing: str = "}"
) -> int | None:
    """
    Return the index just past the delimiter matching js[opening_index],
    skipping over string/template literals and comments — e.g. locate the
    end of an event handler's body (onMouseEnter={e => { ... }}) so every
    statement inside can be scanned, not just the first.
    """
    return JavaScriptFunctionScanner(js)._matching_delimiter(opening_index, opening, closing)


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


def extract_return_block(
    js: str, fn_start: int, fn_end: int, body_start: int | None = None,
) -> str:
    """
    Within the function body [fn_start, fn_end], locate the return statement
    and extract the content between the outer parentheses.

    Handles both 'return (' and 'return(' forms.
    Returns an empty string when no return statement is found.

    body_start (optional): index of the function's own opening '{' (as in
    FunctionBoundary.body_start). When given and the function has a brace
    body, every top-level `return` statement — one brace-depth inside the
    function's own body, e.g. a bare `if (cond) return <X/>;` guard clause —
    is extracted, not just the first one a regex happens to match. A
    component with guard-clause early returns before its main render
    (`if (!user) return <Login/>; if (x) return <X/>; return <Main/>;`)
    previously lost every branch but the first, silently discarding
    whichever one actually renders the screen's real content (see
    docs/changes/C36). Two or more branches are concatenated, each preceded
    by a `{[return_branch:N]}` marker — `{[return_branch:default]}` for the
    last one, treated as the main/default render, matching the common
    `if (guard) return X; ... return <Main/>` idiom. A guard whose return
    sits inside its own block (`if (cond) { return X; }`) is one brace
    deeper and is not detected as a separate branch — same documented
    limitation C21 already accepts for JSX-internal conditionals.
    Omitting body_start (every call site written before this parameter
    existed) keeps the original first-match-only behavior unchanged.
    """
    if not js or fn_start >= fn_end:
        return ""

    window = js[fn_start:fn_end]

    if body_start is not None:
        body_offset = body_start - fn_start
        if 0 <= body_offset < len(window) and window[body_offset] == "{":
            branches = _top_level_return_expressions(window, body_offset)
            if len(branches) > 1:
                return "\n".join(
                    f"{{[return_branch:{'default' if i == len(branches) - 1 else i + 1}]}}\n{jsx}"
                    for i, jsx in enumerate(branches)
                )
            if branches:
                return branches[0]
            return ""

    visual_return = RE_VISUAL_RETURN.search(window)
    selected_return = visual_return or re.search(r"\breturn\s*\(", window)
    if selected_return is None:
        return ""
    # RE_VISUAL_RETURN uses a lookahead, so .end() already sits at the
    # expression start (works for both `return` and arrow `=>` matches).
    # The plain `return\s*\(` fallback still needs the literal offset.
    expression_start = (
        selected_return.end() if visual_return is not None
        else selected_return.start() + len("return")
    )
    while expression_start < len(window) and window[expression_start].isspace():
        expression_start += 1
    scanner = JavaScriptFunctionScanner(window)
    if expression_start < len(window) and window[expression_start] == "(":
        expression_end = scanner._matching_delimiter(expression_start, "(", ")")
        if expression_end is not None:
            return window[expression_start + 1:expression_end - 1].strip()
    expression_end = scanner.expression_end(expression_start)
    return window[expression_start:expression_end].strip()


_RE_BRACE_OR_RETURN = re.compile(r"[{}]|\breturn\b")


def _top_level_return_expressions(window: str, body_start: int) -> list[str]:
    """
    Return the expression text of every `return` statement sitting exactly
    one brace-depth inside window[body_start] (the function's own opening
    '{') — a guard clause like `if (cond) return <X/>;` lives at that depth,
    a callback's own `return` (`useEffect(() => { return cleanup; })`) does
    not, since the callback's own '{' pushes the depth one level deeper.

    Reuses JavaScriptLexicalView's string/comment-aware matching rather than
    re-implementing it, so a `return` or brace inside a string/comment is
    correctly ignored exactly like everywhere else in this module.
    """
    scanner = JavaScriptFunctionScanner(window)
    body_end = scanner._matching_delimiter(body_start, "{", "}")
    if body_end is None:
        body_end = len(window)

    lexical_view = JavaScriptLexicalView.analyze(window)
    depth = 0
    branches: list[str] = []
    for match in lexical_view.executable_matches(_RE_BRACE_OR_RETURN):
        pos = match.start()
        if pos < body_start:
            continue
        if pos >= body_end:
            break
        token = match.group()
        if token == "{":
            depth += 1
            continue
        if token == "}":
            depth -= 1
            continue
        if depth != 1:
            continue  # a return nested deeper than the function's own body
        expr_start = match.end()
        while expr_start < body_end and window[expr_start].isspace():
            expr_start += 1
        if expr_start < body_end and window[expr_start] == "(":
            expr_end = scanner._matching_delimiter(expr_start, "(", ")")
            jsx = window[expr_start + 1:expr_end - 1].strip() if expr_end is not None else ""
        else:
            expr_end = scanner.expression_end(expr_start)
            jsx = window[expr_start:expr_end].strip()
        if jsx:
            branches.append(jsx)
    return branches


def _raw_boundaries(js: str, name_pattern: re.Pattern) -> list[FunctionBoundary]:
    """Match name_pattern against executable source and compute each boundary's
    start/body_start/end, without resolving overlaps between results."""
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

    return boundaries


def _clip_sibling_overlaps(boundaries: list[FunctionBoundary]) -> list[FunctionBoundary]:
    """
    Sort by start and resolve overlaps between adjacent boundaries.

    A boundary that is fully *contained* by its predecessor (a component
    declared inside another component's body, e.g. an arrow-function
    sub-component) is left intact — both boundaries keep their own text.
    Only a *partial* overlap (predecessor's end-detection bled into the next
    sibling) is clipped back to where the next boundary starts.
    """
    boundaries = sorted(boundaries, key=lambda b: b.start)

    for i in range(len(boundaries) - 1):
        if boundaries[i].end >= boundaries[i + 1].end:
            continue  # boundaries[i] fully contains boundaries[i + 1] — nested, keep both
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


def find_function_boundaries(
    js: str, name_pattern: re.Pattern
) -> list[FunctionBoundary]:
    """
    Find all functions whose names match name_pattern and return their
    precise character boundaries.

    The returned list is sorted by start position. Sibling boundaries are
    guaranteed not to overlap: boundary[i].end <= boundary[i+1].start, unless
    boundary[i] fully contains boundary[i+1] (a nested declaration).
    """
    return _clip_sibling_overlaps(_raw_boundaries(js, name_pattern))


def find_all_boundaries(js: str) -> list[FunctionBoundary]:
    """
    Find boundaries for all PascalCase component functions in the JS string,
    covering both `function Name(...)` and `const Name = (...) =>` declaration
    forms. Used as the entry point for the extraction pipeline.
    """
    raw = _raw_boundaries(js, RE_COMP_FN) + _raw_boundaries(js, RE_COMP_ARROW_FN)
    return _clip_sibling_overlaps(raw)


# ── Object-literal parsing (style={{...}} and spread-source const objects) ─────
#
# The regex these two functions replaced (`RE_INLINE_STYLE` / `RE_STYLE_PROP`)
# used plain character classes — `[^}]` for the block, `[^,"'}\n]` for a
# value — to stay closing-brace- and comma-safe. Both classes break the
# instant a *legitimate* JS value contains that character: a template
# literal's `${cond ? a : b}` interpolation carries a `}` that isn't the
# object's own closing brace, and a ternary's quoted branches
# (`disabled ? 'not-allowed' : 'pointer'`) carry commas/quotes inside a
# single value. The two functions below walk the text once, tracking quote/
# template-literal state and bracket depth the same way find_matching_
# delimiter already does for function bodies, so a value is only ever split
# on a comma or closed on a brace that is truly its own.

def iter_style_object_blocks(text: str) -> Iterator[str]:
    """
    Yield the inner content of every `style={{ ... }}` object literal found
    in text, in source order.

    Locates each `{{` pair by its balanced closing `}}` rather than by
    scanning for the first `}` — so a template-literal interpolation nested
    inside the block (`border: \\`1px solid ${C.border2}\\``) cannot cut the
    block short before its real end.
    """
    for match in re.finditer(r"style=\{\{", text):
        object_open = match.end() - 1
        object_close = find_matching_delimiter(text, object_open, "{", "}")
        if object_close is None:
            continue
        yield text[object_open + 1 : object_close - 1]


def split_top_level(text: str, separator: str = ",") -> list[str]:
    """
    Split text on `separator` at bracket depth 0 and outside a quote or
    template literal — the general form of the depth-aware splitting both
    an object literal's `key: value` pairs and a constant array's own
    elements need: a separator inside a nested object, a ternary, or a
    template-literal interpolation must never be mistaken for a top-level
    boundary. One splitter, so the two consumers can't drift apart.
    """
    segments: list[str] = []
    depth = {"(": 0, "[": 0, "{": 0}
    opening_for = {")": "(", "]": "[", "}": "{"}
    quote: str | None = None
    escaped = False
    segment_start = 0

    for index, char in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in "\"'`":
            quote = char
        elif char in depth:
            depth[char] += 1
        elif char in opening_for:
            depth[opening_for[char]] = max(0, depth[opening_for[char]] - 1)
        elif char == separator and not any(depth.values()):
            segments.append(text[segment_start:index])
            segment_start = index + 1

    segments.append(text[segment_start:])
    return segments


def iter_object_literal_pairs(block: str) -> Iterator[tuple[str, str]]:
    """
    Split a JS object-literal body (already unwrapped from its outer
    braces) into its top-level `key: value` pairs, in source order, values
    exactly as written — a quoted string keeps its quotes. An entry with
    no top-level `:` (a `...spread`) is skipped rather than yielded with
    an empty value.

    The raw (non-unwrapped) value is what a caller needs to tell a genuine
    string literal (`label: 'Cardápio'`) apart from a bare identifier or
    expression (`icon: Icon.card`) — see is_quoted_string_literal.
    parse_object_literal_props below is the convenience wrapper for
    callers that only want the unwrapped value.
    """
    for segment in split_top_level(block):
        segment = segment.strip()
        if not segment:
            continue
        key, separator, value = segment.partition(":")
        if not separator:
            continue
        yield key.strip(), value.strip()


def parse_object_literal_props(block: str) -> list[tuple[str, str]]:
    """
    iter_object_literal_pairs, with each value unwrapped to its bare
    content when it's a quoted literal (`'red'` → `red`) — matching
    StyleEntry's existing convention of storing literal values unquoted.
    Any other value (ternary, template literal, identifier, expression) is
    kept as written.
    """
    return [(key, unwrap_quoted_literal(value)) for key, value in iter_object_literal_pairs(block)]


def is_quoted_string_literal(value: str) -> bool:
    """
    True when `value` (as written in source, untrimmed of its own quotes)
    is a single/double-quoted string literal — `'red'`, `"Cardápio"` — as
    opposed to a bare identifier, member expression (`Icon.card`), or a
    backtick template literal (which can embed `${expr}` and so isn't
    static text).
    """
    return len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'"


def unwrap_quoted_literal(value: str) -> str:
    return value[1:-1] if is_quoted_string_literal(value) else value
