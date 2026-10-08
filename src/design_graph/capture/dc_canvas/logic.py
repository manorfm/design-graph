"""
Literal data a DC page's logic class declares — `const papel = [{…}, …]` —
read without running the logic. A list counts when it is written literally,
built by calls to a factory the logic declares (`const mk = (id, label) =>
({ id, label, … })`), or sliced or mapped from such a list; anything else is
left out rather than guessed.
"""

from __future__ import annotations

import re

from design_graph.capture.dc_canvas.literals import Calls, NotALiteral, expression_at, read_literal, string_end

_RE_DECLARATION = re.compile(r"\b(?:const|let|var)\s+([\w$]+)\s*=\s*")
_RE_FACTORY = re.compile(r"(?:\(\s*([\w$]+(?:\s*,\s*[\w$]+)*)?\s*\)|([\w$]+))\s*=>\s*\(\s*(?=\{)")
_RE_LIST_NAME = re.compile(r"[\w$]+")
_RE_SLICE = re.compile(r"\.slice\(\s*(-?\d+)?\s*(?:,\s*(-?\d+)\s*)?\)")
_RE_MAP = re.compile(r"\.map\(")
_RE_STATEMENT_END = re.compile(r"[ \t]*(?:[;,\n]|$)")


def literal_lists(logic: str) -> dict[str, list]:
    """Name → value of every list the logic declares as data, first declaration first."""
    factories = _factories(logic)
    found: dict[str, list] = {}
    for declaration in _RE_DECLARATION.finditer(logic):
        name = declaration.group(1)
        if name not in found:
            value = _list_at(logic, declaration.end(), factories, found)
            if value is not None:
                found[name] = value
    return found


def _factories(logic: str) -> Calls:
    """Each arrow function the logic declares that returns an object: `mk(…)` → that object, its members bound."""
    factories: dict = {}
    for declaration in _RE_DECLARATION.finditer(logic):
        head = _RE_FACTORY.match(logic, declaration.end())
        if head and declaration.group(1) not in factories:
            parameters = head.group(2) or head.group(1) or ""
            factories[declaration.group(1)] = _factory(logic, head.end(), re.findall(r"[\w$]+", parameters))
    return factories


def _factory(logic: str, body: int, parameters: list[str]):
    """A call to the factory whose object starts at `body`: its members read with the parameters bound to the arguments."""
    def call(arguments: list) -> object:
        if len(arguments) != len(parameters):
            raise NotALiteral(f"{len(arguments)} arguments for {len(parameters)} parameters")
        return read_literal(logic, body, dict(zip(parameters, arguments))).value
    return call


def _list_at(logic: str, start: int, factories: Calls, known: dict[str, list]) -> list | None:
    """The list declared at `start` — literal or taken from a known one — after the slices and maps applied to it."""
    if logic.startswith("[", start):
        try:
            literal = read_literal(logic, start, calls=factories)
        except NotALiteral:
            return None
        value, index = literal.value, literal.end
    else:
        name = _RE_LIST_NAME.match(logic, start)
        if not name or name.group() not in known:
            return None
        value, index = known[name.group()], name.end()
    return _derived(value, logic, index)


def _derived(value: list, logic: str, index: int) -> list | None:
    """`value` through the `.slice(…)` and `.map(…)` that follow it — a map keeps each item's data — or None
    when anything else is applied, since what remains could not be told."""
    while True:
        if _RE_STATEMENT_END.match(logic, index):
            return value
        piece = _RE_SLICE.match(logic, index)
        if piece:
            start, stop = (int(bound) if bound else None for bound in piece.groups())
            value, index = value[start:stop], piece.end()
            continue
        mapped = _RE_MAP.match(logic, index)
        if not mapped:
            return None
        closing = _closing(logic, mapped.end() - 1)
        if closing is None:
            return None
        index = closing + 1


def _closing(text: str, start: int) -> int | None:
    """Index of the bracket closing the one opened at `start`, skipping brackets inside strings."""
    depth, index = 0, start
    while index < len(text):
        char = text[index]
        if char in "\"'`":
            index = string_end(text, index)
        elif char in "[{(":
            depth += 1
        elif char in "]})":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def member_expression(logic: str, key: str) -> str | None:
    """
    The expression the logic gives a member named `key` — `pick: () =>
    this.setState({ papel: o.id })` → `() => this.setState({ papel: o.id })` —
    read up to the comma or brace that ends it, strings and nesting respected.
    """
    for match in re.finditer(rf"\b{re.escape(key)}\s*:\s*", logic):
        expression = expression_at(logic, match.end()).strip()
        if expression:
            return expression
    return None


def list_member(logic: str, list_name: str, key: str) -> str | None:
    """
    The member `key` the items of the list `list_name` get — read in that
    list's declaration (`const sen = [...].map((o) => ({ ..., pick: … }))`),
    so two lists giving their items a same-named member each keep their own;
    anywhere in the logic when the list is not declared there.
    """
    declared = re.search(rf"\b(?:const|let|var)\s+{re.escape(list_name)}\s*=\s*", logic) if list_name else None
    scoped = member_expression(expression_at(logic, declared.end()), key) if declared else None
    return scoped or member_expression(logic, key)


_RE_STATE_VARIABLE = re.compile(r"\b(?:const|let|var)\s+([\w$]+)\s*=\s*this\.state\b")
_RE_SELECTION = re.compile(
    r"^(?P<condition>.+?)\s*\?\s*(?P<chosen>'[^']*'|\"[^\"]*\")\s*:\s*(?P<other>'[^']*'|\"[^\"]*\")$", re.S
)
_RE_PICKS_ITEM = re.compile(r"===\s*[\w$]+\.id\b|\b[\w$]+\.id\s*===")


def state_defaults(logic: str) -> list[tuple[str, str]]:
    """
    (name, default) of each state the logic reads with a fallback —
    `s.papel ?? "eng"`, where `s` holds `this.state` — in order, once.
    """
    holders = {"this.state", *(f"{name}" for name in _RE_STATE_VARIABLE.findall(logic))}
    found: dict[str, str] = {}
    for holder in holders:
        pattern = re.compile(rf"(?<![\w$.]){re.escape(holder)}\.([\w$]+)\s*\?\?\s*")
        for match in pattern.finditer(logic):
            found.setdefault(match.group(1), expression_at(logic, match.end()).strip())
    return sorted(found.items(), key=lambda item: logic.find(f".{item[0]}"))


def selection_branches(expression: str) -> tuple[str, str] | None:
    """(value when the item is the selected one, value otherwise) of `x === o.id ? 'a' : 'b'`, or None."""
    match = _RE_SELECTION.match(expression.strip())
    if not match or not _RE_PICKS_ITEM.search(match.group("condition")):
        return None
    return match.group("chosen")[1:-1], match.group("other")[1:-1]
