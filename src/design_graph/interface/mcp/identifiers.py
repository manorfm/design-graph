"""
The names a piece of code uses — handlers, state, helpers — for search.

Kept apart from search.py on purpose: search never compiles a pattern at
all, so a query can never become one. This pattern is fixed; it only ever
reads stored sources.
"""

from __future__ import annotations

import re

_RE_IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]{2,}")
_KEYWORDS = frozenset(
    "function return const let var true false null undefined this new class import export default if else for "
    "while switch case break continue typeof instanceof await async try catch finally throw delete void".split()
)


def identifiers_in(source: str) -> list[str]:
    """Each name of three or more characters the code uses, once, in order — language keywords left out."""
    return [name for name in dict.fromkeys(_RE_IDENTIFIER.findall(source)) if name not in _KEYWORDS]
