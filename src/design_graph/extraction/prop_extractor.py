"""
Extracts declared props from React function component signatures.

Works on the raw JS window for a single component boundary:

    function NavBar({ title, items = [], onClose, variant = 'primary' }) { ... }
        → [ComponentProp(title, required), ComponentProp(items, "[]"), ...]

Handles both `function Name({...})` and `const Name = ({...}) =>` forms.
Rest props (...spread) and positional props (props) are ignored.

Layer: extraction — must not import from graph/ or mcp/.
"""

from __future__ import annotations

import hashlib
import logging

from design_graph.core.models import ComponentProp, FunctionBoundary
from design_graph.core.patterns import RE_DESTRUCTURED_PROPS

logger = logging.getLogger(__name__)

# Maximum number of props to extract per component (guards against malformed JS).
_MAX_PROPS_PER_COMPONENT = 30


def extract_props_from_function_signature(
    js: str,
    boundary: FunctionBoundary,
) -> list[ComponentProp]:
    """
    Parse the destructured prop list from a React component function signature
    and return a list of ComponentProp models.

    Scans only the first 600 characters of the function boundary to stay
    within the signature — the body is irrelevant for prop declarations.
    Returns an empty list when no destructuring pattern is found.
    """
    scan_window = js[boundary.start : boundary.start + 600]
    match = RE_DESTRUCTURED_PROPS.search(scan_window)
    if not match:
        return []

    raw_props = match.group(1)
    entries = _split_by_comma_respecting_brackets(raw_props)

    props: list[ComponentProp] = []
    for entry in entries:
        if len(props) >= _MAX_PROPS_PER_COMPONENT:
            logger.debug(
                "prop_extractor: capped at %d props for %s",
                _MAX_PROPS_PER_COMPONENT,
                boundary.name,
            )
            break

        prop = _parse_prop_entry(entry.strip(), boundary.name)
        if prop is not None:
            props.append(prop)

    logger.debug(
        "prop_extractor: %s — %d props extracted", boundary.name, len(props)
    )
    return props


# ── Private helpers ───────────────────────────────────────────────────────────

def _parse_prop_entry(entry: str, component_name: str) -> ComponentProp | None:
    """
    Parse one entry from a destructured props list.

    Returns None for:
    - Rest/spread props (...rest)
    - TypeScript type-only entries (contain ':' without '=')
    - Entries that are not valid identifiers
    """
    if not entry:
        return None

    # Skip rest/spread props
    if entry.startswith("..."):
        return None

    # Handle default value: "variant = 'primary'" or "disabled = false"
    if "=" in entry:
        name_part, _, default_part = entry.partition("=")
        prop_name = name_part.strip()
        default_value = default_part.strip().strip("'\"")
    else:
        # Skip TypeScript-style type annotations without defaults: "value: string"
        if ":" in entry:
            return None
        prop_name = entry.strip()
        default_value = ""

    # Validate: must be a simple camelCase identifier starting with a lowercase letter
    if not prop_name or not prop_name.isidentifier() or not prop_name[0].islower():
        return None

    prop_id = "prop_" + hashlib.md5(
        f"{component_name}_{prop_name}".encode(), usedforsecurity=False
    ).hexdigest()[:8]

    return ComponentProp(
        id=prop_id,
        component_name=component_name,
        prop_name=prop_name,
        default_value=default_value,
    )


def _split_by_comma_respecting_brackets(text: str) -> list[str]:
    """
    Split a props string by ',' while respecting nested brackets.

    Example:
        "title, items = [], onClose"  →  ["title", " items = []", " onClose"]
        "config = {}"  →  ["config = {}"]   (not split by the comma inside {})
    """
    parts: list[str] = []
    depth = 0
    current: list[str] = []

    for ch in text:
        if ch in "([{":
            depth += 1
            current.append(ch)
        elif ch in ")]}":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)

    if current:
        parts.append("".join(current))

    return parts
