"""
Domain models shared across all layers.

All dataclasses here are immutable by default (frozen=True where possible).
Mutable ones (e.g. ExtractedScreen with sections_count updated post-extraction)
use regular @dataclass with explicit field control.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── Raw parsing output ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RawSources:
    """Output of source_loader.load() — immutable view of the HTML file's content."""

    js: str
    css: str
    inner_html: str
    html_hash: str
    format: str  # "bundled_react" | "tailwind" | "plain_html"


@dataclass(frozen=True)
class FunctionBoundary:
    """
    Exact character-level position of a JavaScript function in the JS string.

    start      — index of "function Name("
    body_start — index of the first "{" (function body open)
    end        — index after the matching "}" (function body close)

    Guarantee: for sibling functions, boundary[i].end <= boundary[i+1].start.
    This property is what makes parallel extraction safe.
    """

    name: str
    start: int
    body_start: int
    end: int


# ── Design tokens ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DesignToken:
    """A reusable visual value extracted from CSS/JS (color, spacing, etc.)."""

    id: str        # deterministic MD5 hash prefix, e.g. "col_a3f2b1"
    category: str  # "color" | "spacing" | "typography" | "shadow" | "radius" | "css_var"
    label: str     # semantic name, e.g. "primary", "space_16", "text_base", "weight_bold"
    value: str     # raw value, e.g. "#ffb81c", "16px", "700"
    usage: int     # occurrence count across css+js


# ── Component prop declarations ───────────────────────────────────────────────

@dataclass(frozen=True)
class ComponentProp:
    """
    A declared prop extracted from a React component's destructured function signature.

    default_value is an empty string when the prop is required (no default);
    a non-empty string carries the literal default (e.g. 'primary', 'false', '1').
    """

    id: str               # deterministic hash: "prop_{MD5[:8]}"
    component_name: str
    prop_name: str        # camelCase prop identifier, e.g. "onClose", "variant"
    default_value: str    # "" = required; otherwise the default literal


# ── Component sub-entities ────────────────────────────────────────────────────

@dataclass(frozen=True)
class StyleEntry:
    """One CSS property/value pair from a component's inline styles."""

    id: str
    element: str   # component name that owns this style
    state: str     # "default" | "hover" | "focus" | "transition"
    property: str  # camelCase CSS property, e.g. "backgroundColor"
    value: str


@dataclass(frozen=True)
class InteractionEntry:
    """A detected mouse/focus interaction on a component."""

    id: str
    trigger: str     # "hover" | "focus"
    css_prop: str
    from_val: str
    to_val: str
    transition: str  # e.g. "all 0.2s ease"


@dataclass(frozen=True)
class TextEntry:
    """A UI string extracted from a component's return block."""

    id: str
    content: str
    text_type: str  # "heading" | "button" | "label" | "placeholder" | "description"
    source: str     # component name
    element: str    # HTML tag context, e.g. "h1", "button"


# ── Extracted domain entities ─────────────────────────────────────────────────

@dataclass
class ExtractedComponent:
    """
    Full extracted representation of a React component function.
    Populated in a single pass over the function body.
    """

    name: str
    comp_type: str      # inferred: "button" | "card" | "modal" | "screen" | etc.
    jsx_snippet: str    # sanitized return() block
    occurrence: int     # how many times this function appears in the JS
    classes: str        # space-separated CSS class names found in className=
    styles: list[StyleEntry] = field(default_factory=list)
    interactions: list[InteractionEntry] = field(default_factory=list)
    texts: list[TextEntry] = field(default_factory=list)
    child_refs: list[str] = field(default_factory=list)   # PascalCase component names referenced in JSX
    props: list[ComponentProp] = field(default_factory=list)  # declared props from function signature


@dataclass
class ExtractedScreen:
    """
    A React function identified as a top-level screen/page.
    sections_count is filled after SectionExtractor runs.
    """

    name: str
    component_refs: list[str] = field(default_factory=list)  # direct children
    sections_count: int = 0


@dataclass(frozen=True)
class ExtractedSection:
    """
    A named visual block within a screen, detected by comment or DOM structure.
    """

    id: str
    screen: str
    name: str
    styles: dict          # prop → value
    component_refs: list[str]
    texts: list[str]
    jsx_snippet: str
    detection_method: str  # "comment" | "structural" | "semantic" | "none"


# ── DOM analysis (plain HTML) ─────────────────────────────────────────────────

@dataclass(frozen=True)
class DOMPattern:
    """A DOM structure that repeats >= N times — candidate for a component."""

    signature: str       # e.g. "div.card>img,h3,p,button"
    count: int
    first_example: str   # truncated HTML of the first occurrence
    inferred_name: str   # e.g. "RestaurantCard"
    semantic_type: str   # "card" | "nav" | "list-item" | etc.


# ── Chunking ──────────────────────────────────────────────────────────────────

@dataclass
class ChunkEnvelope:
    """
    A self-contained fragment of UI structure with navigation metadata.
    Designed for AI consumption: each chunk makes sense without reading siblings.
    """

    chunk_id: str            # slug: [a-z0-9_]+
    breadcrumb: str          # e.g. "RestaurantsPage > Header"
    level: str               # "screen" | "section" | "component"
    parent_id: Optional[str]
    sibling_ids: list[str]
    child_ids: list[str]
    content: str             # sanitized JSX or structured HTML
    tokens_est: int          # len(content) // 4
    component_refs: list[str]
    context_summary: str     # one-line description
    source_screen: str


# ── Build state ───────────────────────────────────────────────────────────────

@dataclass
class BuildState:
    """Persisted state from the previous build run (for incremental builds)."""

    html_hash: str
    last_build: str            # ISO datetime string
    screens: dict[str, str]    # name → content hash
    components: dict[str, int] # name → occurrence count
    source_path: str = ""
    database_path: str = ""
    schema_version: int = 2


@dataclass(frozen=True)
class BuildDiff:
    """What changed between the previous and current build."""

    is_first_build: bool
    screens_added: list[str]
    screens_removed: list[str]
    comps_added: list[str]
    comps_removed: list[str]


@dataclass
class BuildStats:
    """Counts of graph nodes/edges after a completed build."""

    screens: int = 0
    components: int = 0
    tokens: int = 0
    sections: int = 0
    interactions: int = 0
    styles: int = 0
    texts: int = 0
    contains_rels: int = 0
    component_props: int = 0   # ComponentProp nodes from function signature extraction
    section_styles: int = 0    # SECTION_HAS_STYLE edges for section container styles
    duration_seconds: float = 0.0
