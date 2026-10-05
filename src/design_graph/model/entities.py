"""
Design-graph domain entities — the vocabulary every capture produces and
every interface reads: screens, sections, components, props, styles, tokens,
texts, interactions and icons.

Nothing here depends on how a prototype was captured or how the graph is
queried; captures and interfaces depend on this module, never the reverse.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum, IntEnum

# Matches the {[icon:id]} marker IconAsset.__str__ produces, for expansion
# back into full markup by resolve_icon_markers.
RE_ICON_MARKER = re.compile(r'\{\[icon:(icon_[0-9a-f]{8})\]\}')

# A custom-property reference inside a CSS value: `var(--accent)`, `var( --rule , #000)`.
RE_CUSTOM_PROPERTY_REFERENCE = re.compile(r"var\(\s*(--[\w-]+)")

# A raw string candidate that reads as a code artifact rather than visible
# copy: a lowercase/underscore identifier (`flex_start`, `overview`) or a
# color literal (`#1a1a1a`, `rgba(0,0,0,.5)` — the latter caught by its
# `rgba` prefix, not this pattern). Backs TextEntry.reads_as_copy.
RE_IDENTIFIER_SHAPED_TOKEN = re.compile(r"^[a-z_]+$")


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


class ComponentDefinitionStatus(IntEnum):
    """Persistence marker encoded in Component.occurrence without a schema migration."""

    UNRESOLVED = 0


class StrEnum(str, Enum):
    """
    Base for every closed-set value type in this codebase — not just the
    domain fields below; screen_extractor.ScreenRole, the graph catalog's
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


class DetectionMethod(StrEnum):
    COMMENT = "comment"
    STRUCTURAL = "structural"
    SEMANTIC = "semantic"
    LIST_ITEM = "list_item"


class ComponentType(StrEnum):
    """Semantic type of a component — the vocabulary every capture classifies into."""

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


class PropDefault(str):
    """
    A prop's default-value literal as the source declares it (e.g.
    `variant = 'secondary'`).

    An empty value means only that no default was declared — not that callers
    must supply the prop: props are routinely omitted where they are used.
    """

    __slots__ = ()

    @property
    def was_declared(self) -> bool:
        return len(self) > 0

    def as_table_cell(self) -> str:
        return f"`{self}`" if self.was_declared else "—"


@dataclass(frozen=True)
class DesignToken:
    """
    A reusable visual value extracted from CSS/JS (color, spacing, etc.).

    A custom-property token (category CSS_VAR) is named by the property
    itself (`--accent`), so a style value that references it —
    `var(--accent)` — resolves to it. A token defined once per mode (light,
    dark…) is one DesignToken per mode, sharing the label.
    """

    id: EntityId
    category: TokenCategory
    label: str     # semantic name, e.g. "primary", "space_16", "--accent"
    value: str     # raw value, e.g. "#ffb81c", "16px", "700"
    usage: int     # occurrence count across css+js
    mode: str = ""  # the mode this value belongs to ("claro", "dark"…); "" when the prototype has one


@dataclass(frozen=True)
class IconAsset:
    """
    A deduplicated inline SVG icon extracted from a component's markup.

    id is a content hash of `markup` (see EntityId.derive), so the same icon
    reused across components or within one component always resolves to the
    same IconAsset — the graph stores its source once no matter how many
    places render it. str(icon) is the {[icon:id]} marker left in place of
    the markup in a component's source_code; GraphReader expands it back on
    read (see model.graph.reader.GraphReader._resolve_icons).
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


@dataclass(frozen=True)
class ComponentProp:
    """A prop a component declares, with its default value when it has one."""

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

    _MIN_LITERAL_CHARS = 3

    @classmethod
    def create(cls, content: str, text_type: TextType, source: str, element: str = "") -> "TextEntry":
        return cls(
            id=EntityId.derive("txt", f"{source}_{content}"),
            content=content, text_type=text_type, source=source, element=element,
        )

    @staticmethod
    def reads_as_copy(literal: str) -> bool:
        """
        True when a string literal found in code reads as UI copy rather than
        a code artifact a string-literal scan picks up alongside it: an
        identifier-shaped lowercase token (`primary`, `flex_start`), a raw
        color literal (`#1a1a1a`, `rgba(0,0,0,.5)`) or a fragment too short to
        be a label. Length never disqualifies copy — a paragraph is copy.

        Only for literals: text nodes of rendered markup are copy by
        definition and never go through this (see capture.markup).
        """
        c = literal.strip()
        if len(c) < TextEntry._MIN_LITERAL_CHARS:
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


@dataclass
class ExtractedComponent:
    """A reusable piece of UI, as its capture extracted it from the prototype."""

    name: str
    comp_type: ComponentType
    source_code: str    # the markup that renders it, as stored by the capture
    occurrence: int     # how many times it appears in the prototype
    classes: str        # space-separated CSS class names it uses
    styles: list[StyleEntry] = field(default_factory=list)
    interactions: list[InteractionEntry] = field(default_factory=list)
    texts: list[TextEntry] = field(default_factory=list)
    child_refs: list[str] = field(default_factory=list)   # names of the components it renders
    props: list[ComponentProp] = field(default_factory=list)  # declared props from function signature
    icons: list[IconAsset] = field(default_factory=list)  # deduplicated inline SVGs referenced by source_code
    truncated_fields: frozenset[str] = field(default_factory=frozenset)  # e.g. {"styles", "texts"} when a MAX_*_PER_COMPONENT cap was hit
    referenced_data: dict[str, object] = field(default_factory=dict)
    source_lang: str = ""                 # language of source_code, as the capture stated it ("jsx", "html", …)
    source_simplified: bool = False       # the capture replaced parts of the original with placeholders
    declares_inline_styles: bool = False  # the source carries inline styling, captured as Style rows or not
    # {const_name: value} for every module-level constant this component's
    # own body references by name (e.g. ICONS for a component that does
    # `ICONS[name]`) — see extraction/module_data_extractor.py and
    # docs/changes/C39.


@dataclass(frozen=True)
class ScreenLink:
    """A way out of a screen into another — a link, a "Next" button, a back arrow."""

    target: str     # name of the screen it leads to
    label: str = "" # what the user sees on it ("Começar", "Voltar")

    def __post_init__(self) -> None:
        if not self.target.strip():
            raise ValueError("a screen link needs a target screen")


@dataclass
class ExtractedScreen:
    """
    A top-level screen/page. sections_count is filled once its sections are known.

    source_code is the screen's own markup — the shell around its children
    (header, grid, chrome). Screens and components are disjoint, so without
    its own source_code a screen's root markup would be stored nowhere.
    """

    name: str
    component_refs: list[str] = field(default_factory=list)  # direct children
    sections_count: int = 0
    source_code: str = ""
    icons: list[IconAsset] = field(default_factory=list)  # deduplicated inline SVGs referenced by source_code
    source_lang: str = ""
    source_simplified: bool = False
    viewport_width: int = 0                             # px the screen was designed for; 0 = unknown
    viewport_height: int = 0
    links: list[ScreenLink] = field(default_factory=list)  # navigation to other screens
    variant_of: str = ""                                # base screen this one varies, "" when it is a base
    variant_axis: str = ""                              # what varies: "viewport", "mode", …


@dataclass(frozen=True)
class ExtractedSection:
    """
    A named visual block within a screen, detected by comment or DOM structure.
    """

    id: EntityId
    screen: str
    name: str
    styles: dict          # prop → value, from this section's own literal style={{}} objects —
                           # no selector identity (a literal style block isn't textually tied to
                           # which nested element it belongs to), attributed to the section as a
                           # whole. Class-resolved styles live in element_styles instead (C36):
                           # unlike a literal style object, a className carries its own selector,
                           # so folding it into this flat dict would collide two different
                           # elements' same-named property into one slot.
    component_refs: list[str]
    texts: list[str]
    source_code: str
    detection_method: DetectionMethod
    element_styles: list[StyleEntry] = field(default_factory=list)  # CSS-class-resolved, one entry per (selector, property) — see `styles` above
    source_lang: str = ""

    @classmethod
    def create(
        cls, screen: str, name: str, styles: dict, component_refs: list[str],
        texts: list[str], source_code: str, detection_method: DetectionMethod,
        element_styles: list[StyleEntry] | None = None, source_lang: str = "",
    ) -> "ExtractedSection":
        """Comment or structural detection — id keyed by (screen, name)."""
        return cls(
            id=EntityId.derive("sec", f"{screen}_{name}"),
            screen=screen, name=name, styles=styles, component_refs=component_refs,
            texts=texts, source_code=source_code, detection_method=detection_method,
            element_styles=element_styles or [], source_lang=source_lang,
        )

    @classmethod
    def create_semantic(cls, screen: str, name: str, index: int, texts: list[str], source_code: str) -> "ExtractedSection":
        """Semantic (plain-HTML) detection — index included since same-named
        semantic sections can repeat within a screen."""
        return cls(
            id=EntityId.derive("sec", f"{screen}_{name}_{index}"),
            screen=screen, name=name, styles={}, component_refs=[],
            texts=texts, source_code=source_code, detection_method=DetectionMethod.SEMANTIC,
        )

