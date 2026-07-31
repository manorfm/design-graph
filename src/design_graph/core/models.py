"""
Domain models shared across all layers.

All dataclasses here are immutable by default (frozen=True where possible).
Mutable ones (e.g. ExtractedScreen with sections_count updated post-extraction)
use regular @dataclass with explicit field control.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Optional


# ── Identity ───────────────────────────────────────────────────────────────────

class EntityId(str):
    """
    A deterministic, prefixed identifier for a graph entity.

    A plain string subclass — Cypher params, dict keys, and JSON all treat it
    exactly like `str`. Only construction gets richer behavior: `derive()`
    replaces the `prefix + hashlib.md5(seed).hexdigest()[:8]` pattern that
    used to be reimplemented independently across every extractor module.
    """

    __slots__ = ()

    @classmethod
    def derive(cls, prefix: str, seed: str) -> "EntityId":
        digest = hashlib.md5(seed.encode(), usedforsecurity=False).hexdigest()[:8]
        return cls(f"{prefix}_{digest}")

    @classmethod
    def literal(cls, prefix: str, suffix: str) -> "EntityId":
        return cls(f"{prefix}_{suffix}")


# ── Raw parsing output ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RawSources:
    """Output of source_loader.load() — immutable view of the HTML file's content."""

    js: str
    css: str
    inner_html: str
    html_hash: str
    format: SourceFormat
    skipped_entries: int = 0  # bundle entries that failed base64/gzip decode (bundled_react only)


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


class ComponentDefinitionStatus(IntEnum):
    """Persistence marker encoded in Component.occurrence without a schema migration."""

    UNRESOLVED = 0


# ── Closed-set value types ──────────────────────────────────────────────────────

class _StrEnum(str, Enum):
    """
    Base for every closed-set value type below.

    `(str, Enum)` members already behave as their plain value for isinstance
    checks, `+` concatenation, and `json.dumps` — but `Enum.__str__` shadows
    `str.__str__`, so `str(member)`/f-strings/`%s` produce "ClassName.MEMBER"
    instead of the value. Overriding `__str__` once here fixes every seed
    string built via f-string across the codebase, not just the id-derivation
    ones written for this refactor.
    """

    def __str__(self) -> str:
        return str(self.value)


class StyleState(_StrEnum):
    DEFAULT = "default"
    HOVER = "hover"
    FOCUS = "focus"


class InteractionTrigger(_StrEnum):
    HOVER = "hover"
    FOCUS = "focus"


class TextType(_StrEnum):
    HEADING = "heading"
    BUTTON = "button"
    LABEL = "label"
    PLACEHOLDER = "placeholder"
    DESCRIPTION = "description"
    SECTION_TEXT = "section_text"  # section-scoped text (graph/writer.py), not component-scoped


class TokenCategory(_StrEnum):
    COLOR = "color"
    SPACING = "spacing"
    TYPOGRAPHY = "typography"
    SHADOW = "shadow"
    RADIUS = "radius"
    CSS_VAR = "css_var"


class SourceFormat(_StrEnum):
    BUNDLED_REACT = "bundled_react"
    TAILWIND = "tailwind"
    PLAIN_HTML = "plain_html"


class DetectionMethod(_StrEnum):
    COMMENT = "comment"
    STRUCTURAL = "structural"
    SEMANTIC = "semantic"


class ChunkLevel(_StrEnum):
    SCREEN = "screen"
    SECTION = "section"
    COMPONENT = "component"


class ComponentType(_StrEnum):
    """Semantic type of an ExtractedComponent — union of every value the
    React-path inference (component_extractor) and the plain-HTML path
    (plain_html_component_extractor) can produce."""

    MODAL = "modal"
    SCREEN = "screen"
    BUTTON = "button"
    CARD = "card"
    TAB = "tab"
    FORM = "form"
    LIST_ITEM = "list-item"
    BADGE = "badge"
    CHART = "chart"
    NAVIGATION = "navigation"
    TOGGLE = "toggle"
    TABLE = "table"
    COMPONENT = "component"  # fallback/unknown


class SemanticType(_StrEnum):
    """DOM-level semantic category from html_parser._infer_semantic_type —
    distinct value space from ComponentType (e.g. "nav" vs "navigation");
    _SEMANTIC_TYPE_TO_COMP_TYPE maps one to the other."""

    NAV = "nav"
    HEADER = "header"
    FOOTER = "footer"
    CARD = "card"
    MODAL = "modal"
    BADGE = "badge"
    FORM = "form"
    TABLE = "table"
    LIST_ITEM = "list-item"
    COMPONENT = "component"


class PropDefault(str):
    """A React prop's default-value literal. Empty means the prop is required."""

    __slots__ = ()

    @property
    def is_required(self) -> bool:
        return len(self) == 0


# ── Design tokens ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DesignToken:
    """A reusable visual value extracted from CSS/JS (color, spacing, etc.)."""

    id: EntityId
    category: TokenCategory
    label: str     # semantic name, e.g. "primary", "space_16", "text_base", "weight_bold"
    value: str     # raw value, e.g. "#ffb81c", "16px", "700"
    usage: int     # occurrence count across css+js


# ── Component prop declarations ───────────────────────────────────────────────

@dataclass(frozen=True)
class ComponentProp:
    """A declared prop extracted from a React component's destructured function signature."""

    id: EntityId
    component_name: str
    prop_name: str          # camelCase prop identifier, e.g. "onClose", "variant"
    default_value: PropDefault

    @classmethod
    def create(cls, component_name: str, prop_name: str, default_value: str) -> "ComponentProp":
        return cls(
            id=EntityId.derive("prop", f"{component_name}_{prop_name}"),
            component_name=component_name,
            prop_name=prop_name,
            default_value=PropDefault(default_value),
        )


# ── Component sub-entities ────────────────────────────────────────────────────

@dataclass(frozen=True)
class StyleEntry:
    """One CSS property/value pair from a component's inline styles."""

    id: EntityId
    element: str        # component name (or section id, or "class:<name>") that owns this style
    state: StyleState
    property: str        # camelCase CSS property, e.g. "backgroundColor"
    value: str

    @classmethod
    def create(
        cls, element: str, property: str, value: str, state: StyleState = StyleState.DEFAULT,
    ) -> "StyleEntry":
        seed = (
            f"{element}_{property}_{value}" if state == StyleState.DEFAULT
            else f"{element}_{state}_{property}_{value}"
        )
        return cls(id=EntityId.derive("st", seed), element=element, state=state, property=property, value=value)

    @classmethod
    def from_css_class(cls, class_name: str, property: str, value: str) -> "StyleEntry":
        return cls(
            id=EntityId.derive("cls", f"{class_name}:{property}"),
            element=f"class:{class_name}", state=StyleState.DEFAULT, property=property, value=value,
        )

    @classmethod
    def for_section(cls, section_id: str, property: str, value: str) -> "StyleEntry":
        return cls(
            id=EntityId.derive("sec", f"{section_id}_{property}"),
            element=section_id, state=StyleState.DEFAULT, property=property, value=value,
        )


@dataclass(frozen=True)
class InteractionEntry:
    """A detected mouse/focus interaction on a component."""

    id: EntityId
    trigger: InteractionTrigger
    css_prop: str
    from_val: str
    to_val: str
    transition: str  # e.g. "all 0.2s ease"

    @classmethod
    def create(
        cls, element: str, trigger: InteractionTrigger, css_prop: str,
        from_val: str, to_val: str, transition: str,
    ) -> "InteractionEntry":
        """Hover (imperative or state-toggle) and state-toggle focus."""
        return cls(
            id=EntityId.derive("int", f"{element}_{css_prop}_{to_val}"),
            trigger=trigger, css_prop=css_prop, from_val=from_val, to_val=to_val, transition=transition,
        )

    @classmethod
    def from_focus_mutation(cls, element: str, css_prop: str, to_val: str, transition: str) -> "InteractionEntry":
        """Imperative onFocus={e => style.prop = value} — no from_val, seed omits to_val."""
        return cls(
            id=EntityId.derive("int", f"{element}_focus_{css_prop}"),
            trigger=InteractionTrigger.FOCUS, css_prop=css_prop, from_val="", to_val=to_val, transition=transition,
        )


@dataclass(frozen=True)
class TextEntry:
    """A UI string extracted from a component's return block."""

    id: EntityId
    content: str
    text_type: TextType
    source: str      # component name (or section id, for section-scoped text)
    element: str      # HTML tag context, e.g. "h1", "button"

    @classmethod
    def create(cls, content: str, text_type: TextType, source: str, element: str = "") -> "TextEntry":
        return cls(
            id=EntityId.derive("txt", f"{source}_{content}"),
            content=content, text_type=text_type, source=source, element=element,
        )

    @classmethod
    def for_section(cls, section_id: str, text: str) -> "TextEntry":
        return cls(
            id=EntityId.derive("stxt", f"{section_id}_{text}"),
            content=text, text_type=TextType.SECTION_TEXT, source=section_id, element="section",
        )


# ── Extracted domain entities ─────────────────────────────────────────────────

@dataclass
class ExtractedComponent:
    """
    Full extracted representation of a React component function.
    Populated in a single pass over the function body.
    """

    name: str
    comp_type: ComponentType
    jsx_snippet: str    # sanitized return() block
    occurrence: int     # how many times this function appears in the JS
    classes: str        # space-separated CSS class names found in className=
    styles: list[StyleEntry] = field(default_factory=list)
    interactions: list[InteractionEntry] = field(default_factory=list)
    texts: list[TextEntry] = field(default_factory=list)
    child_refs: list[str] = field(default_factory=list)   # PascalCase component names referenced in JSX
    props: list[ComponentProp] = field(default_factory=list)  # declared props from function signature

    @classmethod
    def consolidate(cls, variants: list["ExtractedComponent"]) -> "ExtractedComponent":
        """Merge same-named source definitions into one lossless graph entity."""
        if not variants:
            raise ValueError("component consolidation requires at least one variant")
        names = {variant.name for variant in variants}
        if len(names) != 1:
            raise ValueError("component variants must share the same name")

        jsx_variants = list(dict.fromkeys(
            variant.jsx_snippet for variant in variants if variant.jsx_snippet
        ))
        classes = sorted({
            class_name
            for variant in variants
            for class_name in variant.classes.split()
            if class_name
        })
        styles = {
            item.id: item for variant in variants for item in variant.styles
        }
        interactions = {
            item.id: item for variant in variants for item in variant.interactions
        }
        texts = {
            item.id: item for variant in variants for item in variant.texts
        }
        props = {
            item.id: item for variant in variants for item in variant.props
        }
        return cls(
            name=variants[0].name,
            comp_type=next(
                (variant.comp_type for variant in variants if variant.comp_type != ComponentType.COMPONENT),
                variants[0].comp_type,
            ),
            jsx_snippet="\n\n{/* Source variant */}\n\n".join(jsx_variants),
            occurrence=max(variant.occurrence for variant in variants),
            classes=" ".join(classes),
            styles=list(styles.values()),
            interactions=list(interactions.values()),
            texts=list(texts.values()),
            child_refs=sorted({
                child for variant in variants for child in variant.child_refs
            }),
            props=list(props.values()),
        )


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

    id: EntityId
    screen: str
    name: str
    styles: dict          # prop → value
    component_refs: list[str]
    texts: list[str]
    jsx_snippet: str
    detection_method: DetectionMethod

    @classmethod
    def create(
        cls, screen: str, name: str, styles: dict, component_refs: list[str],
        texts: list[str], jsx_snippet: str, detection_method: DetectionMethod,
    ) -> "ExtractedSection":
        """Comment or structural detection — id keyed by (screen, name)."""
        return cls(
            id=EntityId.derive("sec", f"{screen}_{name}"),
            screen=screen, name=name, styles=styles, component_refs=component_refs,
            texts=texts, jsx_snippet=jsx_snippet, detection_method=detection_method,
        )

    @classmethod
    def create_semantic(cls, screen: str, name: str, index: int, texts: list[str], jsx_snippet: str) -> "ExtractedSection":
        """Semantic (plain-HTML) detection — index included since same-named
        semantic sections can repeat within a screen."""
        return cls(
            id=EntityId.derive("sec", f"{screen}_{name}_{index}"),
            screen=screen, name=name, styles={}, component_refs=[],
            texts=texts, jsx_snippet=jsx_snippet, detection_method=DetectionMethod.SEMANTIC,
        )


# ── DOM analysis (plain HTML) ─────────────────────────────────────────────────

@dataclass(frozen=True)
class DOMPattern:
    """A DOM structure that repeats >= N times — candidate for a component."""

    signature: str       # e.g. "div.card>img,h3,p,button"
    count: int
    first_example: str   # truncated HTML of the first occurrence
    inferred_name: str   # e.g. "RestaurantCard"
    semantic_type: SemanticType


# ── Chunking ──────────────────────────────────────────────────────────────────

@dataclass
class ChunkEnvelope:
    """
    A self-contained fragment of UI structure with navigation metadata.
    Designed for AI consumption: each chunk makes sense without reading siblings.
    """

    chunk_id: str            # slug: [a-z0-9_]+
    breadcrumb: str          # e.g. "RestaurantsPage > Header"
    level: ChunkLevel
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
    extracted_components: int = 0
    unresolved_components: int = 0
    tokens: int = 0
    sections: int = 0
    interactions: int = 0
    styles: int = 0
    texts: int = 0
    contains_rels: int = 0
    component_props: int = 0   # ComponentProp nodes from function signature extraction
    section_styles: int = 0    # SECTION_HAS_STYLE edges for section container styles
    duration_seconds: float = 0.0
