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

from design_graph.core.patterns import RE_ICON_MARKER, RE_IDENTIFIER_SHAPED_TOKEN


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

class StrEnum(str, Enum):
    """
    Base for every closed-set value type in this codebase — not just the
    domain fields below; screen_extractor.ScreenRole, graph_catalog's
    GraphArtifactKind/GraphSelectionSource, and cli.validate.ValidationSeverity
    use it too.

    `(str, Enum)` members already behave as their plain value for isinstance
    checks, `+` concatenation, and `json.dumps` — but `Enum.__str__` shadows
    `str.__str__`, so `str(member)`/f-strings/`%s` produce "ClassName.MEMBER"
    instead of the value. Overriding `__str__` once here fixes that for every
    consumer, instead of each one needing to remember `.value` everywhere.
    """

    def __str__(self) -> str:
        return str(self.value)


class StyleState(StrEnum):
    DEFAULT = "default"
    HOVER = "hover"
    FOCUS = "focus"


class InteractionTrigger(StrEnum):
    HOVER = "hover"
    FOCUS = "focus"


class TextType(StrEnum):
    HEADING = "heading"
    BUTTON = "button"
    LABEL = "label"
    PLACEHOLDER = "placeholder"
    DESCRIPTION = "description"
    SECTION_TEXT = "section_text"  # section-scoped text (graph/writer.py), not component-scoped
    TOOLTIP = "tooltip"  # title/aria-label/alt — descriptive, not part of the visible content flow


class TokenCategory(StrEnum):
    COLOR = "color"
    SPACING = "spacing"
    TYPOGRAPHY = "typography"
    SHADOW = "shadow"
    RADIUS = "radius"
    CSS_VAR = "css_var"


class SourceFormat(StrEnum):
    BUNDLED_REACT = "bundled_react"
    TAILWIND = "tailwind"
    PLAIN_HTML = "plain_html"


class DetectionMethod(StrEnum):
    COMMENT = "comment"
    STRUCTURAL = "structural"
    SEMANTIC = "semantic"


class ChunkLevel(StrEnum):
    SCREEN = "screen"
    SECTION = "section"
    COMPONENT = "component"


class ComponentType(StrEnum):
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


class SemanticType(StrEnum):
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
    """
    A React prop's default-value literal, as declared in the component's
    destructured function signature (e.g. `variant = 'secondary'`).

    JSX has no required/optional prop system, so an empty value here means
    only that no default was declared — not that callers must supply the
    prop. A prop is routinely omitted at call sites (guarded by `&&`,
    rendered safely as `undefined`, etc.) with no default in sight.
    """

    __slots__ = ()

    @property
    def was_declared(self) -> bool:
        return len(self) > 0

    def as_table_cell(self) -> str:
        return f"`{self}`" if self.was_declared else "—"


# ── JSX sanitization markers ────────────────────────────────────────────────────

class JsxMarkerKind(StrEnum):
    """The three ways sanitize_jsx collapses a dynamic JSX expression."""

    LIST = "list"
    CONDITIONAL = "conditional"
    EITHER = "either"


@dataclass(frozen=True)
class JsxMarker:
    """
    A typed placeholder standing in for one dynamic JSX expression — a
    `.map()` render, a `&&` short-circuit, or a `? :` ternary — so an AI
    agent can see which component renders there without the surrounding
    JS logic.

    LIST and CONDITIONAL name exactly one component; EITHER names two, in
    source order (then-branch, else-branch — e.g. `error ? <A/> : <B/>`
    becomes `("A", "B")`). The count is validated on construction so a
    caller can never assemble a marker that doesn't match its own kind.
    """

    kind: JsxMarkerKind
    component_names: tuple[str, ...]

    def __post_init__(self) -> None:
        expected = 2 if self.kind is JsxMarkerKind.EITHER else 1
        if len(self.component_names) != expected:
            raise ValueError(
                f"{self.kind} marker takes {expected} component name(s), "
                f"got {self.component_names!r}"
            )

    def __str__(self) -> str:
        return f"{{[{self.kind}:{'|'.join(self.component_names)}]}}"


# Literal markers sanitize_jsx (extraction/jsx_sanitizer.py) leaves behind
# for a collapsed region that isn't a named-component reference — JsxMarker
# above covers list/conditional/either, which always name one or two
# components. Defined once here, and imported by jsx_sanitizer.py to build
# its replacement text, so a marker's written form and its detection in
# JsxSnippet.was_sanitized can never drift apart.
JSX_HANDLER_MARKER               = "={[handler]}"
JSX_ARROW_FN_MARKER              = ".[fn]"
JSX_STYLE_BLOCK_COLLAPSE_SUFFIX  = ", ... }}"
JSX_BARE_EXPRESSION_MARKER       = "{...}"


class JsxSnippet(str):
    """
    A JSX snippet as stored on a Component/Section node — already passed
    through sanitize_jsx during extraction, never the original source text.

    `.was_sanitized` names whether any collapse marker survived censorship
    in this particular snippet, so a caller (mcp.tools.get_full_jsx) can
    tell a genuinely complete snippet from one where sanitize_jsx already
    discarded part of the original JSX. CappedJsx (mcp/tools.py) captures
    the same kind of fact for a *display-time* cut applied to an already-
    stored snippet; this is the *extraction-time* cut baked into the
    snippet itself, which no display-side limit can recover.
    """

    __slots__ = ()

    _MARKERS: tuple[str, ...] = (
        JSX_HANDLER_MARKER,
        JSX_ARROW_FN_MARKER,
        JSX_STYLE_BLOCK_COLLAPSE_SUFFIX,
        JSX_BARE_EXPRESSION_MARKER,
        *(f"{{[{kind}:" for kind in JsxMarkerKind),
    )

    @property
    def was_sanitized(self) -> bool:
        return any(marker in self for marker in self._MARKERS)


# ── Design tokens ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DesignToken:
    """A reusable visual value extracted from CSS/JS (color, spacing, etc.)."""

    id: EntityId
    category: TokenCategory
    label: str     # semantic name, e.g. "primary", "space_16", "text_base", "weight_bold"
    value: str     # raw value, e.g. "#ffb81c", "16px", "700"
    usage: int     # occurrence count across css+js


# ── Icon assets ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class IconAsset:
    """
    A deduplicated inline SVG icon extracted from a component's markup.

    id is a content hash of `markup` (see EntityId.derive), so the same icon
    reused across components or within one component always resolves to the
    same IconAsset — the graph stores its source once no matter how many
    places render it. str(icon) is the {[icon:id]} marker left in place of
    the markup in a component's jsx_snippet; GraphReader expands it back on
    read (see graph.reader.GraphReader._resolve_icons).
    """

    id: EntityId
    markup: str     # the raw <svg>...</svg> (or self-closing <svg .../>) source

    @classmethod
    def create(cls, markup: str) -> "IconAsset":
        return cls(id=EntityId.derive("icon", markup), markup=markup)

    def __str__(self) -> str:
        return f"{{[icon:{self.id}]}}"


def resolve_icon_markers(text: str, markup_by_id: dict[str, str]) -> str:
    """
    Expand every {[icon:id]} marker in `text` back into its full markup,
    the inverse of IconAsset.__str__. A marker with no entry in
    `markup_by_id` is left as-is rather than silently erased.

    Shared by every reader of icon-bearing text — GraphReader (looking up
    markup in the graph) and the standalone chunk exporter (looking up
    markup in a freshly extracted, not-yet-written icon list) — so the
    marker format has exactly one place that knows how to undo it.
    """
    if not text or "{[icon:" not in text:
        return text
    return RE_ICON_MARKER.sub(lambda m: markup_by_id.get(m.group(1), m.group(0)), text)


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
    # Raw @media condition this rule is scoped to (e.g. "(max-width:600px)"),
    # or None when the rule is unconditional. Orthogonal to `state`: state is
    # an interaction axis (hover/focus), media is a viewport axis — C29 kept
    # them deliberately separate rather than folding breakpoint into state.
    media: str | None = None

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
    def from_css_class(
        cls, class_name: str, property: str, value: str,
        state: StyleState = StyleState.DEFAULT, media: str | None = None,
    ) -> "StyleEntry":
        parts = [class_name]
        if state != StyleState.DEFAULT:
            parts.append(str(state))
        if media is not None:
            parts.append(media)
        parts.append(property)
        seed = ":".join(parts)
        return cls(
            id=EntityId.derive("cls", seed),
            element=f"class:{class_name}", state=state, property=property, value=value, media=media,
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
    """A UI string extracted from a component's return block, a section,
    or a module-level constant array (see extraction.module_text_extractor)."""

    id: EntityId
    content: str
    text_type: TextType
    source: str      # component name, section id, or module-level constant name
    element: str      # HTML tag context, e.g. "h1", "button"

    _MIN_CONTENT_CHARS = 3
    _MAX_CONTENT_CHARS = 80

    @classmethod
    def create(cls, content: str, text_type: TextType, source: str, element: str = "") -> "TextEntry":
        return cls(
            id=EntityId.derive("txt", f"{source}_{content}"),
            content=content, text_type=text_type, source=source, element=element,
        )

    @staticmethod
    def is_plausible_content(candidate: str) -> bool:
        """
        True when `candidate` reads as real, visible UI copy rather than a
        code artifact a naive string-literal scan can pick up alongside
        genuine text: an identifier-shaped lowercase token (`primary`,
        `flex_start`) or a raw color literal (`#1a1a1a`, `rgba(0,0,0,.5)`).

        The single definition every extractor that classifies string
        literals as UI text shares, so "plausible" can't drift between
        call sites — component-scoped text (component_extractor) and
        module-level constant-array text (module_text_extractor) apply
        the exact same judgment.
        """
        c = candidate.strip()
        if not (TextEntry._MIN_CONTENT_CHARS <= len(c) <= TextEntry._MAX_CONTENT_CHARS):
            return False
        if RE_IDENTIFIER_SHAPED_TOKEN.match(c) or c.startswith(("#", "rgba")):
            return False
        return True

    @classmethod
    def for_section(cls, section_id: str, text: str) -> "TextEntry":
        return cls(
            id=EntityId.derive("stxt", f"{section_id}_{text}"),
            content=text, text_type=TextType.SECTION_TEXT, source=section_id, element="section",
        )


# ── Extracted domain entities ─────────────────────────────────────────────────

def _label_jsx_variants(jsx_variants: list[str]) -> str:
    """
    Join same-named component definitions found at multiple points in the
    source, labeling which one actually executes.

    JS hoists `function Name(...)` declarations fully — a later declaration
    of the same name in the same scope completely replaces an earlier one,
    so only the last one ever runs. Silently concatenating them would let an
    agent mistake unreachable code for the real implementation.
    """
    if len(jsx_variants) <= 1:
        return jsx_variants[0] if jsx_variants else ""

    last = len(jsx_variants) - 1
    labeled = [
        f"{{/* Variant {i + 1}/{len(jsx_variants)} — "
        + ("live (last declaration wins in JS)" if i == last else "shadowed by a later declaration, never executes")
        + f" */}}\n{jsx}"
        for i, jsx in enumerate(jsx_variants)
    ]
    return "\n\n".join(labeled)


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
    icons: list[IconAsset] = field(default_factory=list)  # deduplicated inline SVGs referenced by jsx_snippet
    truncated_fields: frozenset[str] = field(default_factory=frozenset)  # e.g. {"styles", "texts"} when a MAX_*_PER_COMPONENT cap was hit

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
        jsx_snippet = _label_jsx_variants(jsx_variants)
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
        icons = {
            item.id: item for variant in variants for item in variant.icons
        }
        truncated_fields = frozenset(
            field_name for variant in variants for field_name in variant.truncated_fields
        )
        # Render order comes from the *live* variant (the last declaration —
        # same "last declaration wins in JS" criterion _label_jsx_variants
        # already uses above to pick which jsx_snippet actually executes),
        # not a union sorted alphabetically. A variant order this component
        # only referenced in a shadowed, dead declaration is still included
        # — for completeness, matching the union semantics this dedup
        # already had — just appended after the live variant's real order
        # instead of taking equal precedence with it.
        live_variant = variants[-1]
        seen_children: set[str] = set()
        child_refs: list[str] = []
        for child in live_variant.child_refs:
            if child not in seen_children:
                seen_children.add(child)
                child_refs.append(child)
        for variant in variants:
            for child in variant.child_refs:
                if child not in seen_children:
                    seen_children.add(child)
                    child_refs.append(child)
        return cls(
            name=variants[0].name,
            comp_type=next(
                (variant.comp_type for variant in variants if variant.comp_type != ComponentType.COMPONENT),
                variants[0].comp_type,
            ),
            jsx_snippet=jsx_snippet,
            occurrence=max(variant.occurrence for variant in variants),
            classes=" ".join(classes),
            styles=list(styles.values()),
            interactions=list(interactions.values()),
            texts=list(texts.values()),
            child_refs=child_refs,
            props=list(props.values()),
            icons=list(icons.values()),
            truncated_fields=truncated_fields,
        )


@dataclass
class ExtractedScreen:
    """
    A React function identified as a top-level screen/page.
    sections_count is filled after SectionExtractor runs.

    jsx_snippet is the screen's own return-block — the shell around its
    children (header, grid, chrome) — captured the same way an
    ExtractedComponent's is. Screens and components are deliberately
    disjoint (coordinator.extract_react: "a screen boundary must never
    also be extracted as a component"), so without its own jsx_snippet a
    screen's root markup would never be stored anywhere.
    """

    name: str
    component_refs: list[str] = field(default_factory=list)  # direct children
    sections_count: int = 0
    jsx_snippet: str = ""
    icons: list[IconAsset] = field(default_factory=list)  # deduplicated inline SVGs referenced by jsx_snippet


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
    last_diff: "BuildDiff | None" = None  # what this build changed relative to the one before it


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
    icons: int = 0
    sections: int = 0
    interactions: int = 0
    styles: int = 0
    texts: int = 0
    contains_rels: int = 0
    component_props: int = 0   # ComponentProp nodes from function signature extraction
    section_styles: int = 0    # SECTION_HAS_STYLE edges for section container styles
    write_errors: int = 0      # Non-duplicate write failures during this build (should be 0)
    duration_seconds: float = 0.0
