"""
CSS class rule extractor and Tailwind resolver.

Parses CSS text into a class-name → [CssRule] map and resolves className strings
into StyleEntry objects. Supports custom CSS rules and falls back to a curated
subset of Tailwind utility classes when no custom rule is found.

Guardrail G1: this module must not import from extraction/, graph/, or mcp/.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass

from design_graph.core.models import StyleEntry

logger = logging.getLogger(__name__)

# ── Domain types ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CssRule:
    """A single CSS property/value pair extracted from a class rule."""

    selector: str   # e.g. ".flex"
    property: str   # e.g. "display"
    value: str      # e.g. "flex"


# ── Regex ─────────────────────────────────────────────────────────────────────

# Matches .classname { ... } — simple class selectors only (no pseudo-classes, no element selectors)
_RE_SIMPLE_CLASS_BLOCK = re.compile(
    r'\.([a-zA-Z][a-zA-Z0-9_-]*)\s*\{([^}]+)\}',
    re.MULTILINE,
)

# Matches property: value; inside a CSS block
_RE_CSS_PROPERTY = re.compile(
    r'([a-z][a-z0-9-]*)\s*:\s*([^;}{]+?)\s*(?:;|$)',
    re.MULTILINE,
)


# ── Tailwind numeric class generator ─────────────────────────────────────────
#
# Tailwind spacing scale: class key → CSS rem value.
# Each unit = 0.25rem (4px). Fractional keys (0.5, 1.5, …) use their string
# representation as-is to match the Tailwind class name format.

_TAILWIND_SPACING_SCALE: tuple[tuple[str, str], ...] = (
    ("0",    "0px"),
    ("0.5",  "0.125rem"),
    ("1",    "0.25rem"),
    ("1.5",  "0.375rem"),
    ("2",    "0.5rem"),
    ("2.5",  "0.625rem"),
    ("3",    "0.75rem"),
    ("3.5",  "0.875rem"),
    ("4",    "1rem"),
    ("5",    "1.25rem"),
    ("6",    "1.5rem"),
    ("7",    "1.75rem"),
    ("8",    "2rem"),
    ("9",    "2.25rem"),
    ("10",   "2.5rem"),
    ("11",   "2.75rem"),
    ("12",   "3rem"),
    ("14",   "3.5rem"),
    ("16",   "4rem"),
    ("20",   "5rem"),
    ("24",   "6rem"),
    ("28",   "7rem"),
    ("32",   "8rem"),
    ("36",   "9rem"),
    ("40",   "10rem"),
    ("44",   "11rem"),
    ("48",   "12rem"),
    ("52",   "13rem"),
    ("56",   "14rem"),
    ("60",   "15rem"),
    ("64",   "16rem"),
    ("72",   "18rem"),
    ("80",   "20rem"),
    ("96",   "24rem"),
)

_TAILWIND_MAX_WIDTHS: dict[str, str] = {
    "max-w-xs":         "20rem",
    "max-w-sm":         "24rem",
    "max-w-md":         "28rem",
    "max-w-lg":         "32rem",
    "max-w-xl":         "36rem",
    "max-w-2xl":        "42rem",
    "max-w-3xl":        "48rem",
    "max-w-4xl":        "56rem",
    "max-w-5xl":        "64rem",
    "max-w-6xl":        "72rem",
    "max-w-7xl":        "80rem",
    "max-w-full":       "100%",
    "max-w-screen-sm":  "640px",
    "max-w-screen-md":  "768px",
    "max-w-screen-lg":  "1024px",
    "max-w-screen-xl":  "1280px",
    "max-w-none":       "none",
}


def _build_tailwind_numeric_entries() -> dict[str, list[tuple[str, str]]]:
    """
    Generate the numeric portion of the Tailwind class map programmatically.

    Covers:
      - Sizing:  w-{n}, h-{n}, min-h-{n}, min-w-{n}
      - Spacing: p/px/py/pt/pb/pl/pr-{n}, m/mx/my/mt/mb/ml/mr-{n}, gap/gap-x/gap-y-{n}
      - Grid:    grid-cols-{1..12}, col-span-{1..12}, row-span-{1..6}
      - Max-width: semantic aliases from _TAILWIND_MAX_WIDTHS

    Kept separate from _TAILWIND_BUILTINS so the static map stays readable.
    """
    entries: dict[str, list[tuple[str, str]]] = {}

    for key, val in _TAILWIND_SPACING_SCALE:
        entries[f"w-{key}"]     = [("width",           val)]
        entries[f"h-{key}"]     = [("height",          val)]
        entries[f"p-{key}"]     = [("padding",         val)]
        entries[f"px-{key}"]    = [("padding-left",    val), ("padding-right",  val)]
        entries[f"py-{key}"]    = [("padding-top",     val), ("padding-bottom", val)]
        entries[f"pt-{key}"]    = [("padding-top",     val)]
        entries[f"pb-{key}"]    = [("padding-bottom",  val)]
        entries[f"pl-{key}"]    = [("padding-left",    val)]
        entries[f"pr-{key}"]    = [("padding-right",   val)]
        entries[f"m-{key}"]     = [("margin",          val)]
        entries[f"mx-{key}"]    = [("margin-left",     val), ("margin-right",   val)]
        entries[f"my-{key}"]    = [("margin-top",      val), ("margin-bottom",  val)]
        entries[f"mt-{key}"]    = [("margin-top",      val)]
        entries[f"mb-{key}"]    = [("margin-bottom",   val)]
        entries[f"ml-{key}"]    = [("margin-left",     val)]
        entries[f"mr-{key}"]    = [("margin-right",    val)]
        entries[f"gap-{key}"]   = [("gap",             val)]
        entries[f"gap-x-{key}"] = [("column-gap",      val)]
        entries[f"gap-y-{key}"] = [("row-gap",         val)]

    # Auto margins
    entries["mx-auto"] = [("margin-left", "auto"), ("margin-right", "auto")]
    entries["my-auto"] = [("margin-top",  "auto"), ("margin-bottom", "auto")]
    entries["m-auto"]  = [("margin", "auto")]

    # Grid layout
    for n in range(1, 13):
        entries[f"grid-cols-{n}"] = [("grid-template-columns", f"repeat({n}, minmax(0, 1fr))")]
        entries[f"col-span-{n}"]  = [("grid-column",  f"span {n} / span {n}")]
    for n in range(1, 7):
        entries[f"row-span-{n}"]  = [("grid-row", f"span {n} / span {n}")]

    # Max-width semantic aliases
    for cls, val in _TAILWIND_MAX_WIDTHS.items():
        entries[cls] = [("max-width", val)]

    return entries


# ── Tailwind built-in fallback map ────────────────────────────────────────────
#
# A curated subset of Tailwind CSS utility classes covering the most common
# layout, spacing, typography, and visual patterns found in prototypes.
# This map is used as fallback when the class is not found in the custom rule_map.
# Numeric sizing classes are generated by _build_tailwind_numeric_entries() and
# merged below to keep the static map readable.

_TAILWIND_BUILTINS: dict[str, list[tuple[str, str]]] = {
    # Display
    "flex":        [("display", "flex")],
    "inline-flex": [("display", "inline-flex")],
    "block":       [("display", "block")],
    "inline-block":[("display", "inline-block")],
    "inline":      [("display", "inline")],
    "grid":        [("display", "grid")],
    "hidden":      [("display", "none")],

    # Flexbox / Grid alignment
    "items-start":   [("align-items", "flex-start")],
    "items-center":  [("align-items", "center")],
    "items-end":     [("align-items", "flex-end")],
    "items-stretch": [("align-items", "stretch")],
    "justify-start":   [("justify-content", "flex-start")],
    "justify-center":  [("justify-content", "center")],
    "justify-end":     [("justify-content", "flex-end")],
    "justify-between": [("justify-content", "space-between")],
    "justify-around":  [("justify-content", "space-around")],
    "flex-col":  [("flex-direction", "column")],
    "flex-row":  [("flex-direction", "row")],
    "flex-wrap": [("flex-wrap", "wrap")],
    "flex-1":    [("flex", "1 1 0%")],
    "shrink-0":  [("flex-shrink", "0")],
    "grow":      [("flex-grow", "1")],

    # Gap
    "gap-0": [("gap", "0px")],
    "gap-1": [("gap", "0.25rem")],
    "gap-2": [("gap", "0.5rem")],
    "gap-3": [("gap", "0.75rem")],
    "gap-4": [("gap", "1rem")],
    "gap-5": [("gap", "1.25rem")],
    "gap-6": [("gap", "1.5rem")],
    "gap-8": [("gap", "2rem")],
    "gap-10":[("gap", "2.5rem")],
    "gap-12":[("gap", "3rem")],

    # Padding (all sides)
    "p-0": [("padding", "0px")],
    "p-1": [("padding", "0.25rem")],
    "p-2": [("padding", "0.5rem")],
    "p-3": [("padding", "0.75rem")],
    "p-4": [("padding", "1rem")],
    "p-5": [("padding", "1.25rem")],
    "p-6": [("padding", "1.5rem")],
    "p-8": [("padding", "2rem")],

    # Padding X / Y
    "px-1": [("padding-left", "0.25rem"), ("padding-right", "0.25rem")],
    "px-2": [("padding-left", "0.5rem"),  ("padding-right", "0.5rem")],
    "px-3": [("padding-left", "0.75rem"), ("padding-right", "0.75rem")],
    "px-4": [("padding-left", "1rem"),    ("padding-right", "1rem")],
    "px-5": [("padding-left", "1.25rem"), ("padding-right", "1.25rem")],
    "px-6": [("padding-left", "1.5rem"),  ("padding-right", "1.5rem")],
    "px-8": [("padding-left", "2rem"),    ("padding-right", "2rem")],
    "py-1": [("padding-top", "0.25rem"), ("padding-bottom", "0.25rem")],
    "py-2": [("padding-top", "0.5rem"),  ("padding-bottom", "0.5rem")],
    "py-3": [("padding-top", "0.75rem"), ("padding-bottom", "0.75rem")],
    "py-4": [("padding-top", "1rem"),    ("padding-bottom", "1rem")],
    "py-5": [("padding-top", "1.25rem"), ("padding-bottom", "1.25rem")],
    "py-6": [("padding-top", "1.5rem"),  ("padding-bottom", "1.5rem")],
    "py-8": [("padding-top", "2rem"),    ("padding-bottom", "2rem")],

    # Margin
    "m-0": [("margin", "0px")],
    "m-auto": [("margin", "auto")],
    "mx-auto": [("margin-left", "auto"), ("margin-right", "auto")],

    # Width / Height
    "w-full":   [("width", "100%")],
    "w-screen": [("width", "100vw")],
    "h-full":   [("height", "100%")],
    "h-screen": [("height", "100vh")],
    "min-h-screen": [("min-height", "100vh")],
    "min-w-0": [("min-width", "0px")],

    # Typography — font size
    "text-xs":  [("font-size", "0.75rem")],
    "text-sm":  [("font-size", "0.875rem")],
    "text-base":[("font-size", "1rem")],
    "text-lg":  [("font-size", "1.125rem")],
    "text-xl":  [("font-size", "1.25rem")],
    "text-2xl": [("font-size", "1.5rem")],
    "text-3xl": [("font-size", "1.875rem")],
    "text-4xl": [("font-size", "2.25rem")],

    # Typography — font weight
    "font-thin":       [("font-weight", "100")],
    "font-light":      [("font-weight", "300")],
    "font-normal":     [("font-weight", "400")],
    "font-medium":     [("font-weight", "500")],
    "font-semibold":   [("font-weight", "600")],
    "font-bold":       [("font-weight", "700")],
    "font-extrabold":  [("font-weight", "800")],

    # Text alignment / decoration
    "text-left":    [("text-align", "left")],
    "text-center":  [("text-align", "center")],
    "text-right":   [("text-align", "right")],
    "uppercase":    [("text-transform", "uppercase")],
    "lowercase":    [("text-transform", "lowercase")],
    "capitalize":   [("text-transform", "capitalize")],
    "truncate":     [("overflow", "hidden"), ("text-overflow", "ellipsis"), ("white-space", "nowrap")],
    "line-clamp-1": [("overflow", "hidden"), ("-webkit-line-clamp", "1")],
    "line-clamp-2": [("overflow", "hidden"), ("-webkit-line-clamp", "2")],
    "whitespace-nowrap": [("white-space", "nowrap")],

    # Border radius
    "rounded":      [("border-radius", "0.25rem")],
    "rounded-sm":   [("border-radius", "0.125rem")],
    "rounded-md":   [("border-radius", "0.375rem")],
    "rounded-lg":   [("border-radius", "0.5rem")],
    "rounded-xl":   [("border-radius", "0.75rem")],
    "rounded-2xl":  [("border-radius", "1rem")],
    "rounded-full": [("border-radius", "9999px")],
    "rounded-none": [("border-radius", "0px")],

    # Border
    "border":       [("border-width", "1px")],
    "border-0":     [("border-width", "0px")],
    "border-2":     [("border-width", "2px")],
    "border-t":     [("border-top-width", "1px")],
    "border-b":     [("border-bottom-width", "1px")],

    # Overflow
    "overflow-hidden":   [("overflow", "hidden")],
    "overflow-auto":     [("overflow", "auto")],
    "overflow-y-auto":   [("overflow-y", "auto")],
    "overflow-x-hidden": [("overflow-x", "hidden")],

    # Position
    "relative": [("position", "relative")],
    "absolute": [("position", "absolute")],
    "fixed":    [("position", "fixed")],
    "sticky":   [("position", "sticky")],
    "inset-0":  [("inset", "0")],
    "top-0":    [("top", "0")],
    "bottom-0": [("bottom", "0")],
    "left-0":   [("left", "0")],
    "right-0":  [("right", "0")],

    # Z-index
    "z-0":   [("z-index", "0")],
    "z-10":  [("z-index", "10")],
    "z-20":  [("z-index", "20")],
    "z-30":  [("z-index", "30")],
    "z-50":  [("z-index", "50")],
    "z-auto":[("z-index", "auto")],

    # Opacity / cursor / pointer
    "opacity-0":        [("opacity", "0")],
    "opacity-50":       [("opacity", "0.5")],
    "opacity-100":      [("opacity", "1")],
    "cursor-pointer":   [("cursor", "pointer")],
    "cursor-default":   [("cursor", "default")],
    "pointer-events-none": [("pointer-events", "none")],

    # Shadow
    "shadow":    [("box-shadow", "0 1px 3px 0 rgb(0 0 0/0.1)")],
    "shadow-md": [("box-shadow", "0 4px 6px -1px rgb(0 0 0/0.1)")],
    "shadow-lg": [("box-shadow", "0 10px 15px -3px rgb(0 0 0/0.1)")],
    "shadow-none": [("box-shadow", "none")],

    # Transition
    "transition":        [("transition-property", "color,background-color,border-color,opacity,box-shadow,transform")],
    "transition-colors": [("transition-property", "color,background-color,border-color")],
    "duration-150":      [("transition-duration", "150ms")],
    "duration-200":      [("transition-duration", "200ms")],
    "duration-300":      [("transition-duration", "300ms")],
    "ease-in-out":       [("transition-timing-function", "cubic-bezier(0.4,0,0.2,1)")],

    # Space-between utility (uses gap on modern browsers)
    "space-x-2": [("column-gap", "0.5rem")],
    "space-x-4": [("column-gap", "1rem")],
    "space-y-2": [("row-gap", "0.5rem")],
    "space-y-4": [("row-gap", "1rem")],
}

# Merge numeric classes — generated entries do not override hand-crafted entries
# (static map takes precedence via the order of the merge).
_TAILWIND_BUILTINS = {**_build_tailwind_numeric_entries(), **_TAILWIND_BUILTINS}


# ── Public API ────────────────────────────────────────────────────────────────

def extract_css_rules(css_text: str) -> dict[str, list[CssRule]]:
    """
    Parse CSS text and return a map of class_name → [CssRule].

    Only simple class selectors (.classname { property: value; }) are captured.
    Pseudo-classes (:hover, :focus), element selectors (div), and ID selectors (#id)
    are deliberately ignored — they cannot be resolved from className strings.
    """
    if not css_text or not css_text.strip():
        return {}

    result: dict[str, list[CssRule]] = {}
    try:
        for m in _RE_SIMPLE_CLASS_BLOCK.finditer(css_text):
            cls_name = m.group(1)
            body = m.group(2)
            rules: list[CssRule] = []
            for pm in _RE_CSS_PROPERTY.finditer(body):
                prop = pm.group(1).strip()
                val  = pm.group(2).strip()
                if prop and val:
                    rules.append(CssRule(f".{cls_name}", prop, val))
            if rules:
                result[cls_name] = rules
    except Exception as exc:  # noqa: BLE001
        logger.warning("css_class_resolver: failed to parse CSS — %s", exc)

    logger.debug("css_class_resolver: extracted %d class rules from CSS", len(result))
    return result


def resolve_classes(
    class_string: str,
    rule_map: dict[str, list[CssRule]],
) -> list[StyleEntry]:
    """
    Resolve a className string into StyleEntry objects.

    Resolution order per class name:
    1. Custom rule_map entry (from parsed CSS) — takes priority
    2. Tailwind built-in fallback map

    Returns [] for empty/whitespace class strings.
    Each entry has state="default" and element="class:{class_name}".
    Unknown classes that appear in neither map are silently skipped.
    """
    if not class_string or not class_string.strip():
        return []

    entries: list[StyleEntry] = []
    seen_props: set[str] = set()

    for cls in class_string.split():
        cls = cls.strip()
        if not cls:
            continue

        # Priority 1: custom rule_map
        custom_rules = rule_map.get(cls)
        if custom_rules:
            for rule in custom_rules:
                prop_key = f"{cls}:{rule.property}"
                if prop_key not in seen_props:
                    seen_props.add(prop_key)
                    entries.append(_make_style_entry(cls, rule.property, rule.value))
            continue

        # Priority 2: Tailwind built-in
        builtin = _TAILWIND_BUILTINS.get(cls)
        if builtin:
            for prop, val in builtin:
                prop_key = f"{cls}:{prop}"
                if prop_key not in seen_props:
                    seen_props.add(prop_key)
                    entries.append(_make_style_entry(cls, prop, val))

    logger.debug(
        "css_class_resolver: resolved %d classes → %d style entries",
        len(class_string.split()),
        len(entries),
    )
    return entries


# ── Private helpers ───────────────────────────────────────────────────────────

def _make_style_entry(cls_name: str, prop: str, value: str) -> StyleEntry:
    """Create a StyleEntry for a CSS class-resolved property."""
    sid = f"cls_{hashlib.md5(f'{cls_name}:{prop}'.encode()).hexdigest()[:8]}"
    return StyleEntry(
        id=sid,
        element=f"class:{cls_name}",
        state="default",
        property=prop,
        value=value,
    )
