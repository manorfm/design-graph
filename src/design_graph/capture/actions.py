"""
What an event handler does, read from how it is written — shared by every
capture whose prototypes handle events in JavaScript.

An effect is a plain reading of the handler, in the order it happens:
"muda estado X" (`setX(…)`, `this.setState({ x: … })`), "repassa ao pai
onX" (a callback prop the parent decides), "chama f" (any other function).
The handler itself is always kept next to it, as written.
"""

from __future__ import annotations

import re

_RE_EFFECT = re.compile(
    r"this\.setState\(\s*\{(?P<keys>[^}]*)\}"
    r"|\bset(?P<state>[A-Z][\w$]*)\s*\("
    r"|\b(?P<prop>on[A-Z][\w$]*)\b"
    r"|(?P<call>[A-Za-z_$][\w$.]*)\s*\("
)
_RE_STATE_KEY = re.compile(r"([\w$]+)\s*:")
_RE_NAME = re.compile(r"^[\w$.]+$")
_RE_INTERPOLATION = re.compile(r"^\{\{\s*(.*?)\s*\}\}$")
_NOT_CALLS = frozenset({"function", "if", "for", "while", "switch", "return", "catch"})


def effect_of(handler: str) -> str:
    """Everything the handler does, in order, each once — or what it calls when it is just a name."""
    text = handler.strip()
    interpolated = _RE_INTERPOLATION.match(text)
    if interpolated:
        text = interpolated.group(1)
    if _RE_NAME.match(text):
        return _prop_or_call(text)
    effects: list[str] = []
    for match in _RE_EFFECT.finditer(text):
        if match.group("keys") is not None:
            effects += [f"muda estado {key}" for key in _RE_STATE_KEY.findall(match.group("keys"))]
        elif match.group("state"):
            effects.append(f"muda estado {match.group('state')[0].lower()}{match.group('state')[1:]}")
        elif match.group("prop"):
            effects.append(f"repassa ao pai {match.group('prop')}")
        elif match.group("call") not in _NOT_CALLS:
            effects.append(f"chama {match.group('call')}")
    return " · ".join(dict.fromkeys(effects)) or "executa código"


def _prop_or_call(name: str) -> str:
    last = name.rsplit(".", 1)[-1]
    is_prop = last.startswith("on") and last[2:3].isupper()
    return f"repassa ao pai {last}" if is_prop and "." not in name else f"chama {name}"


def trigger_of(attribute: str) -> str:
    """The event an attribute listens to: `onClick` → click, `sc-camel-on-click` → click."""
    if "on-" in attribute:
        return attribute.rsplit("on-", 1)[1].lower()
    return attribute[2:].lower() if attribute.startswith("on") else attribute.lower()
