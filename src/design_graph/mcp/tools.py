"""
MCP tool implementations and dispatcher.

Each tool method receives a GraphReader and validated arguments, and returns
a Markdown-formatted string. No Kuzu connections, no file I/O here.

ToolDispatcher.pick_reader() resolves which prototype to use:
  Priority: explicit doc= argument → session active_doc → auto-select → error
"""

from __future__ import annotations

import json
import logging

from design_graph.core.graph_catalog import GraphDocumentName
from design_graph.core.models import ComponentType, JsxSnippet, PropDefault, StyleState, TokenCategory
from design_graph.extraction.component_extractor import extract_component
from design_graph.graph.reader import GraphReader
from design_graph.mcp.search import search
from design_graph.parsing.js_parser import find_all_boundaries

logger = logging.getLogger(__name__)

# Default page size for list_components — the only listing tool that had no
# cap at all (search/get_screen_full/get_component_spec already truncate).
_DEFAULT_LIST_COMPONENTS_LIMIT = 100

# validate_component_implementation re-runs the same regex-based extractor
# used for a whole prototype bundle, but over agent-submitted text instead
# of a local file — the one MCP tool whose input isn't bounded by "however
# big this local prototype happens to be". A real component's stored
# jsx_snippet is itself capped at MAX_JSX_SNIPPET_CHARS (8_000); this is a
# generous multiple of that, not a tight fit, so it never rejects a
# legitimate submission while still bounding the computational cost of an
# oversized jsx_source (accidental or adversarial, e.g. an agent misled by
# prompt injection inside the prototype's own HTML).
_MAX_VALIDATION_JSX_SOURCE_CHARS = 20_000

# Synthetic wrapper name for validate_component_implementation. Must be
# plain PascalCase, no leading underscore — find_all_boundaries only
# recognizes function names matching the same convention real React
# component names use, exactly as it would for any bundle it parses.
_VALIDATION_WRAPPER_NAME = "DesignGraphValidationCandidate"


def _extract_validation_candidate(jsx_source: str):
    """
    Re-extract an agent-submitted JSX expression using the same
    component_extractor.extract_component the build pipeline itself uses —
    wrapped in a synthetic function declaration so find_all_boundaries can
    locate it (extract_component has no entry point for bare JSX; a real
    prototype bundle never contains one either).

    No rule_map/tag_rule_map/palette is passed: those come from the whole
    prototype's own stylesheet, which doesn't exist for a standalone
    snippet. Concretely, this means className-resolved styles (custom CSS
    classes and Tailwind color utilities) are NOT captured here even when
    they would be in a real build — only inline style={{}} objects, JSX
    child references, and text content are reliably extracted. Spread
    references (style={{...shared}}) also resolve to nothing, for the same
    "no whole-file context" reason component_extractor's own spread
    resolution already documents.
    """
    synthetic_js = f"function {_VALIDATION_WRAPPER_NAME}() {{\n  return (\n{jsx_source}\n  );\n}}"
    boundaries = find_all_boundaries(synthetic_js)
    if not boundaries:
        return None
    return extract_component(synthetic_js, boundaries[0], 1, {})


# ── Output helpers ────────────────────────────────────────────────────────────

def _truncation_notice(total: int, shown: int, recoverable_via: str | None = None) -> str | None:
    """
    Return a Markdown blockquote notice when a list was cut, else None.

    recoverable_via: when a real escape hatch exists for what got cut (only
    styles do today, via get_full_styles), the exact call to make — same
    "never truncate without naming the way back" convention already used by
    _truncated_fields_notice and CappedJsx.notice for jsx_snippet/component
    truncation. None (every non-style caller) keeps the notice as it was
    before this parameter existed.
    """
    if total <= shown:
        return None
    notice = f"> ... +{total - shown} mais"
    if recoverable_via:
        notice += f" — chame `get_full_styles({recoverable_via})` para a lista completa"
    return notice


def _truncated_fields_notice(
    truncated_fields: str | list[str] | None,
    recoverable_via: str | None = None,
) -> str | None:
    """
    Blockquote warning when extraction hit a MAX_*_PER_COMPONENT cap for one
    or more fields (styles/interactions/texts/classes) on this component.

    Accepts either the raw comma-separated string stored on the Component
    node (get_component/get_component_spec) or the already-split list shape
    used by get_screen_full — same fact, two call sites with different
    intermediate shapes. Without this, an agent reading a "complete-looking"
    spec has no way to tell it was cut, not just short.
    """
    fields = (
        [f for f in truncated_fields.split(",") if f]
        if isinstance(truncated_fields, str)
        else list(truncated_fields or [])
    )
    if not fields:
        return None
    field_list = ", ".join(fields)
    suffix = f" Chame get_full_jsx('{recoverable_via}') para o JSX bruto." if recoverable_via else ""
    return f"> ⚠ Extração truncada em: {field_list} — esta spec pode estar incompleta.{suffix}"


class CappedJsx(str):
    """
    A JSX/markup snippet capped to a display limit, aware of its own cut.

    Mirrors PropDefault (core/models.py): a fact about the value — whether it
    was cut, and by how much — lives on the value itself instead of being
    recomputed from a raw length comparison at every render site.
    """

    __slots__ = ("full_length",)

    def __new__(cls, raw: str, limit: int) -> CappedJsx:
        obj = str.__new__(cls, raw[:limit])
        obj.full_length = len(raw)
        return obj

    @property
    def was_cut(self) -> bool:
        return self.full_length > len(self)

    def notice(self, recoverable_via: str | None) -> str | None:
        """
        A Markdown blockquote naming what was cut, or None when nothing was.

        recoverable_via: component name to pass get_full_jsx() when that tool
        can recover the rest. get_full_jsx lifts the CappedJsx length limit
        applied here, not the jsx_sanitizer markers already baked into the
        stored snippet — it only matches Component nodes, so callers
        rendering a section pass None instead of a false lead.
        """
        if not self.was_cut:
            return None
        cut = self.full_length - len(self)
        if recoverable_via:
            return f"> ... +{cut} caracteres (chame get_full_jsx('{recoverable_via}') para o JSX completo)"
        return f"> ... +{cut} caracteres cortados"


def _props_table_lines(props: list[dict]) -> list[str]:
    """
    A one-line honesty note plus a Prop/Default Markdown table.

    No "Required" column: JSX has no required/optional prop system, so a
    missing default is not proof a prop is required — only PropDefault's
    verifiable fact (whether a default exists, and what it is) is shown.
    """
    lines = [
        "> A missing default does not mean the prop is required — JSX enforces no such contract; check real usage before assuming.",
        "| Prop | Default |",
        "|---|---|",
    ]
    for p in props:
        prop_default = PropDefault(p["default_value"])
        lines.append(f"| `{p['prop_name']}` | {prop_default.as_table_cell()} |")
    return lines


_MIN_JSX_LENGTH_FOR_SCREEN_STRUCTURE_GAP = 200


class ScreenStructureGap:
    """
    True when a screen's own JSX is non-trivial but the section/component
    extraction cascade produced nothing to show it — no comment marker, no
    padding-styled div, and no raw-markup list gave section_extractor
    anything to anchor a Section on, and the screen references no Component
    either. Only meaningful where Sections and Components are already known
    to be empty for this screen — get_screen_full checks that before
    constructing this, the same call-site pattern StyleExtractionGap uses.
    """

    __slots__ = ("exists",)

    def __init__(self, jsx_snippet: str) -> None:
        self.exists = len(jsx_snippet or "") >= _MIN_JSX_LENGTH_FOR_SCREEN_STRUCTURE_GAP

    def notice(self, recoverable_via: str) -> str | None:
        if not self.exists:
            return None
        return (
            f"> ⚠ Nenhuma estrutura extraída para '{recoverable_via}' — containers, "
            f"classes, textos e ícones condicionais podem estar invisíveis aqui. "
            f"Chame get_full_jsx('{recoverable_via}') para o JSX bruto."
        )


class StyleExtractionGap:
    """
    True when a component's JSX declares inline styles but the graph has no
    structured Style rows for it — usually because every value is a runtime
    expression (`hsl(${hue}...)`, a ternary, a prop reference) rather than a
    literal the extractor can store. Only meaningful where styles are
    already known to be empty: an empty Styles section alone can't tell
    "no styling" apart from this case.
    """

    __slots__ = ("exists",)

    def __init__(self, jsx_snippet: str) -> None:
        self.exists = "style={" in (jsx_snippet or "")

    def notice(self) -> str | None:
        if not self.exists:
            return None
        return (
            "> No structured styles extracted — this component's styling is "
            "likely computed at runtime (template literals, ternaries); read "
            "the JSX for actual values."
        )


def _dedupe_styles_by_property(styles: list[dict]) -> list[dict]:
    """
    Collapse multiple rows for the same CSS property into one, joining
    distinct values with " | ".

    Conditional/mapped JSX (`color: i === 2 ? col : 'white'`) produces
    several style rows sharing one property name — truncating the raw list
    to a fixed cap can crowd out genuinely distinct properties before the
    reader ever sees them. Deduping by property first means the cap always
    bounds distinct properties, not raw rows.
    """
    values_by_property: dict[str, list[str]] = {}
    for entry in styles:
        values = values_by_property.setdefault(entry["property"], [])
        if entry["value"] not in values:
            values.append(entry["value"])
    return [
        {"property": prop, "value": " | ".join(values)}
        for prop, values in values_by_property.items()
    ]


_SECTION_STYLE_GROUP_CAP = 8


def _section_style_group_lines(
    styles_by_element: dict[str, list[dict]], recoverable_via: str,
) -> list[str]:
    """
    Render a section's styles_by_element as Markdown, one sub-list per CSS
    selector — the section-level counterpart to get_component_spec's
    "Styles — {state}" grouping, grouped by selector instead of state (see
    docs/changes/C36: a flat property list gave no way to tell which of a
    section's several nested selectors a given value belonged to).
    """
    lines: list[str] = []
    for selector, raw_styles in sorted(styles_by_element.items()):
        styles = _dedupe_styles_by_property(raw_styles)
        lines.append(f"- **{selector}**")
        for s in styles[:_SECTION_STYLE_GROUP_CAP]:
            lines.append(f"  - `{s['property']}`: `{s['value']}`")
        notice = _truncation_notice(len(styles), _SECTION_STYLE_GROUP_CAP, recoverable_via=recoverable_via)
        if notice:
            lines.append(f"  {notice}")
    return lines


# ── Tool schema definitions (MCP protocol) ────────────────────────────────────

def _doc_param() -> dict:
    return {
        "type": "string",
        "description": (
            "Prototype name (e.g. 'ipede-v7'). Required when multiple prototypes "
            "are loaded. Use list_screens to see available names."
        ),
    }


TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "list_screens",
        "description": "Lists all screens in all loaded prototypes, grouped by document.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_screen",
        "description": (
            "Returns a screen's structural overview: section names, component list (names and types) "
            "and screen-level texts. Does NOT include component styles, props or JSX. "
            "Use get_screen_full when you need to implement or replicate the screen. "
            "Always pass 'doc' when multiple prototypes are loaded."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Screen name (e.g. RestaurantsPage)"},
                "doc":  _doc_param(),
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_section",
        "description": "Returns visual details of a specific section within a screen.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "screen":  {"type": "string", "description": "Screen name"},
                "section": {"type": "string", "description": "Section name or partial name"},
                "doc":     _doc_param(),
            },
            "required": ["screen", "section"],
        },
    },
    {
        "name": "get_component",
        "description": (
            "Returns a component's implementation: JSX, styles (default/hover/focus), "
            "design tokens used, texts, interactions, and child components."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Component name (e.g. SectionCard)"},
                "doc":  _doc_param(),
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_tokens",
        "description": (
            "Returns design tokens (color, spacing, typography, shadow, radius, "
            "css_var). Always call before writing any color, spacing, typography, "
            "shadow or radius value. "
            "Pass screen to scope the list to tokens that screen's own components "
            "actually use, instead of every token in the whole prototype ranked by "
            "overall frequency — the global list can't tell you which hex is that "
            "screen's canvas."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Token category. Omit for all tokens.",
                    "enum": [c.value for c in TokenCategory],
                },
                "screen": {
                    "type": "string",
                    "description": "Screen name. Omit for every token in the prototype.",
                },
                "doc": _doc_param(),
            },
            "required": [],
        },
    },
    {
        "name": "find_token_usage",
        "description": "Given a token value or label, returns which components and screens use it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "value": {"type": "string", "description": "Token value or label (e.g. '#FFB81C', 'primary')"},
                "doc":   _doc_param(),
            },
            "required": ["value"],
        },
    },
    {
        "name": "search",
        "description": (
            "Search across screens, components, tokens and texts in all prototypes. "
            "Supports Portuguese terms (botão, modal, tabela, seção, hover, etc.)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search term (PT or EN)"}},
            "required": ["query"],
        },
    },
    {
        "name": "impact",
        "description": "Given a component or token, returns which screens and sections would be affected by a change.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Component or token name"},
                "doc":  _doc_param(),
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_full_jsx",
        "description": "Returns a component's complete sanitized JSX, without the display length cap other tools apply. Dynamic expressions (.map/&&/ternary) still appear as typed markers ({[conditional:X]} etc) — this recovers what CappedJsx truncated, not the original pre-sanitization source. Use when get_component truncated details.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Component or screen name"},
                "doc":  _doc_param(),
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_full_styles",
        "description": "Returns a component's or a screen section's complete style list, without the display cap other tools apply ('+N mais'). The get_full_jsx equivalent for styles. Pass name= for a component, or screen= + section= for a screen section. Use when get_section/get_screen_full/get_component_spec truncated a style table.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name":    {"type": "string", "description": "Component name (mutually exclusive with screen/section)"},
                "screen":  {"type": "string", "description": "Screen name (use together with section)"},
                "section": {"type": "string", "description": "Section name or partial name (use together with screen)"},
                "doc":     _doc_param(),
            },
        },
    },
    {
        "name": "get_component_interactions",
        "description": "Returns hover/focus interaction effects for a component.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Component name"},
                "doc":  _doc_param(),
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_component_children",
        "description": (
            "Returns the direct child components rendered by a parent component. "
            "Uses the CONTAINS relationship built during prototype analysis."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Parent component name"},
                "doc":  _doc_param(),
            },
            "required": ["name"],
        },
    },
    {
        "name": "list_components",
        "description": (
            "Lists all components in the prototype, optionally filtered by semantic type. "
            f"Types: {', '.join(c.value for c in ComponentType)}. "
            "Returns name, type and occurrence count sorted by frequency. "
            f"Response is capped at {_DEFAULT_LIST_COMPONENTS_LIMIT} rows by default (most-used "
            "first) — pass limit for a different page size, or comp_type to filter instead."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "comp_type": {
                    "type": "string",
                    "description": f"Filter by type: {'|'.join(c.value for c in ComponentType)}",
                },
                "limit": {
                    "type": "integer",
                    "description": f"Max rows to return. Default {_DEFAULT_LIST_COMPONENTS_LIMIT}.",
                },
                "doc": _doc_param(),
            },
            "required": [],
        },
    },
    {
        "name": "get_component_spec",
        "description": (
            "Returns the complete spec of a component structured for screen reconstruction: "
            "styles grouped by state (default/hover/focus), design tokens, texts, interactions, "
            "parent/child hierarchy, and which screens use it. If any of the component's classes "
            "carry an @media-scoped override, those values appear in a separate 'Estilos "
            "responsivos' section labeled with their raw condition — never mixed into the "
            "default styles above. This is the only tool that surfaces @media data; all other "
            "style-reading tools only ever return the unconditional value. "
            "Use instead of get_component when building or reproducing UI."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Component name (partial name accepted)"},
                "doc":  _doc_param(),
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_component_full",
        "description": (
            "Returns the full component tree rooted at name: the component itself plus "
            "every descendant reachable via CONTAINS (up to 3 levels deep), each with its "
            "own styles, tokens, texts, interactions, props and children, in render order. "
            "Use instead of get_component_spec + repeated get_component_children calls when "
            "reconstructing one complex component in isolation (a modal, a form, a card with "
            "nested widgets) — one call instead of cascading through every grandchild."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Root component name (partial name accepted)"},
                "doc":  _doc_param(),
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_build_diff",
        "description": (
            "Returns what changed in this prototype's most recent build relative to the "
            "build before it: screens and components added or removed. Answers 'what "
            "changed since I last looked' without re-reading the whole prototype. Reflects "
            "the last time `design-graph <file.html>` was actually run, not live source changes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "doc": _doc_param(),
            },
            "required": [],
        },
    },
    {
        "name": "validate_component_implementation",
        "description": (
            "Compares JSX you wrote against a component's stored spec (children, default-state "
            "styles, texts) and reports discrepancies. Best-effort, not a full re-extraction: "
            "it re-parses jsx_source in isolation, so it reliably catches missing/extra child "
            "components and missing inline styles/texts, but CANNOT verify styles that came from "
            "the prototype's own CSS classes or Tailwind color utilities (e.g. bg-blue-500) — "
            "those require the original stylesheet, which isn't available for a standalone "
            "snippet. Treat a clean report as 'no red flags found', not proof of a pixel-perfect "
            "match. Pass jsx_source as the JSX expression only (what get_full_jsx returns), not "
            f"a full function declaration, and under {_MAX_VALIDATION_JSX_SOURCE_CHARS} characters."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Component name to compare against (partial name accepted)"},
                "jsx_source": {"type": "string", "description": "The JSX expression you implemented, e.g. '<button style={{color: \"red\"}}>OK</button>'"},
                "doc": _doc_param(),
            },
            "required": ["name", "jsx_source"],
        },
    },
    {
        "name": "get_component_props",
        "description": (
            "Returns the declared props (API) of a component: prop names, "
            "whether each is required or optional, and default values. "
            "Use before instantiating a component to know what can be configured."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Component name (partial name accepted)"},
                "doc":  _doc_param(),
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_screen_layout",
        "description": (
            "Returns the layout profile (display, width, height, flex/grid properties) "
            "for every component on a screen. "
            "Use this before reconstructing a screen to understand spatial structure."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Screen name (e.g. RestaurantsPage)"},
                "doc":  _doc_param(),
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_screen_full",
        "description": (
            "Returns everything needed to implement or reconstruct a screen from the prototype: "
            "all sections (with styles, texts, component refs and JSX), "
            "all components (with styles grouped by state, design tokens, texts, "
            "interactions, props and children), and layout profiles for spatial structure. "
            "Use this as the first call when asked to implement, replicate or evolve a screen."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Screen name (e.g. RestaurantsPage)"},
                "doc":  _doc_param(),
            },
            "required": ["name"],
        },
    },
    {
        "name": "set_prototype",
        "description": (
            "Set the active prototype for this session. "
            "All subsequent calls without doc= will use this prototype. "
            "Call with no arguments to check the current selection."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Prototype name to activate. Omit to check current."},
            },
            "required": [],
        },
    },
]


# ── Dispatcher ────────────────────────────────────────────────────────────────

class ToolDispatcher:
    """Resolves the correct reader and delegates to per-tool methods."""

    def __init__(self, readers: list[tuple[str, GraphReader]]) -> None:
        self._readers = readers

    def pick_reader(
        self, doc: str | None, active_doc: str
    ) -> tuple[GraphReader | None, str | None]:
        """
        Resolve which reader to use.
        Returns (reader, None) on success, (None, error_message) on failure.
        """
        if not self._readers:
            return None, (
                "No graphs loaded. Build one first:\n"
                "  design-graph <prototype.html>"
            )

        if doc:
            reader = self._find_reader(doc)
            if reader:
                return reader, None
            available = ", ".join(f"'{n}'" for n, _ in self._readers)
            return None, (
                f"Prototype '{doc}' not found.\n"
                f"Available: {available}\n"
                f"Use list_screens to see all loaded prototypes."
            )

        if active_doc:
            reader = self._find_reader(active_doc)
            if reader:
                return reader, None
            available = ", ".join(f"'{n}'" for n, _ in self._readers)
            return None, (
                f"Active prototype '{active_doc}' not found in loaded graphs.\n"
                f"Available: {available}\n"
                f"Call set_prototype(name='...') to update."
            )

        if len(self._readers) == 1:
            return self._readers[0][1], None

        names = ", ".join(f"'{n}'" for n, _ in self._readers)
        return None, (
            f"Multiple prototypes loaded: {names}\n"
            f"Call set_prototype(name='...') to select one, "
            f"or pass doc= to this call."
        )

    def dispatch(self, tool_name: str, args: dict, active_doc: str) -> str:
        """Route a tool call to the appropriate method."""
        doc  = args.get("doc")
        name = args.get("name", "")

        if tool_name == "list_screens":
            return self.list_screens()

        if tool_name == "search":
            return self.tool_search(args.get("query", ""))

        reader, err = self.pick_reader(doc, active_doc)
        if err:
            return err

        dispatch_map = {
            "get_component_props":       lambda: self.get_component_props(reader, name),
            "get_screen_layout":         lambda: self.get_screen_layout(reader, name),
            "get_screen_full":           lambda: self.get_screen_full(reader, name),
            "get_screen":                lambda: self.get_screen(reader, name),
            "get_section":               lambda: self.get_section(reader, args.get("screen", ""), args.get("section", "")),
            "get_component":             lambda: self.get_component(reader, name),
            "get_tokens":                lambda: self.get_tokens(reader, args.get("category"), args.get("screen")),
            "find_token_usage":          lambda: self.find_token_usage(reader, args.get("value", "")),
            "impact":                    lambda: self.impact(reader, name),
            "get_full_jsx":              lambda: self.get_full_jsx(reader, name),
            "get_full_styles":           lambda: self.get_full_styles(reader, name, args.get("screen", ""), args.get("section", "")),
            "get_component_interactions": lambda: self.get_component_interactions(reader, name),
            "get_component_children":    lambda: self.get_component_children(reader, name),
            "list_components":           lambda: self.list_components(reader, args.get("comp_type"), args.get("limit")),
            "get_component_spec":        lambda: self.get_component_spec(reader, name),
            "get_component_full":        lambda: self.get_component_full(reader, name),
            "get_build_diff":            lambda: self.get_build_diff(reader),
            "validate_component_implementation": lambda: self.validate_component_implementation(
                reader, name, args.get("jsx_source", ""),
            ),
        }

        fn = dispatch_map.get(tool_name)
        if not fn:
            available = ", ".join(dispatch_map.keys())
            return f"Unknown tool: {tool_name}. Available: {available}"

        return fn()

    # ── Tool methods ──────────────────────────────────────────────────────────

    def get_component_props(self, reader: GraphReader, name: str) -> str:
        """Return declared props for a component as a Markdown table."""
        props = reader.get_component_props(name)
        if not props:
            return (
                f"No declared props found for '{name}'. "
                "The component may use positional props, TypeScript interfaces, or have no props."
            )
        lines = [f"# Props: {name}\n", *_props_table_lines(props)]
        logger.debug("tools: get_component_props(%s) — %d props", name, len(props))
        return "\n".join(lines)

    def get_screen_layout(self, reader: GraphReader, name: str) -> str:
        """Return layout profiles for all components on a screen as Markdown."""
        profiles = reader.get_screen_layout(name)
        if not profiles:
            return f"Screen '{name}' not found or has no components with layout data."

        lines = [f"# Layout: {name}\n"]
        for p in profiles:
            lines.append(f"## {p['component_name']}")
            layout_pairs = [
                ("display",          p.get("display")),
                ("position",         p.get("position")),
                ("width",            p.get("width")),
                ("height",           p.get("height")),
                ("padding",          p.get("padding")),
                ("padding-top",      p.get("padding_top")),
                ("padding-right",    p.get("padding_right")),
                ("padding-bottom",   p.get("padding_bottom")),
                ("padding-left",     p.get("padding_left")),
                ("margin",           p.get("margin")),
                ("margin-top",       p.get("margin_top")),
                ("margin-right",     p.get("margin_right")),
                ("margin-bottom",    p.get("margin_bottom")),
                ("margin-left",      p.get("margin_left")),
                ("flex-direction",   p.get("flex_direction")),
                ("align-items",      p.get("align_items")),
                ("justify-content",  p.get("justify_content")),
                ("gap",              p.get("gap")),
                ("overflow",         p.get("overflow")),
                ("z-index",          p.get("z_index")),
            ]
            for css_prop, val in layout_pairs:
                if val is not None:
                    lines.append(f"- `{css_prop}`: `{val}`")
            for extra_prop, extra_val in p.get("extra_layout", {}).items():
                lines.append(f"- `{extra_prop}`: `{extra_val}`")
            lines.append("")
        logger.debug("tools: get_screen_layout(%s) — %d components", name, len(profiles))
        return "\n".join(lines)

    def list_screens(self) -> str:
        lines = ["# Telas disponíveis\n"]
        for doc_name, reader in self._readers:
            screens = reader.list_screens()
            if not screens:
                continue
            lines.append(f"## {doc_name}")
            for s in screens:
                top = ", ".join(s.get("top_components", []))
                lines.append(f"**{s['name']}** ({s['component_count']} componentes)")
                if top:
                    lines.append(f"  → {top}")
            lines.append("")
        return "\n".join(lines) if len(lines) > 1 else "Nenhuma tela encontrada."

    def get_screen_full(self, reader: GraphReader, name: str) -> str:
        """
        Render the complete screen spec as Markdown for AI agent consumption.

        Output structure:
          # Screen heading + counts
          ## Sections — each with styles, component refs, texts and JSX
          ## Components — each with styles-by-state, tokens, interactions, props, children, JSX

        Layout data (display, align-items, ...) lives in each component's own
        "Styles — default" table, not a separate section — get_screen_layout
        is the tool for callers who want only the layout summary.
        """
        spec = reader.get_screen_full(name)
        if not spec:
            all_screens = [s["name"] for s in reader.list_screens()]
            return (
                f"Screen '{name}' not found. "
                f"Available: {', '.join(all_screens) or 'none'}"
            )

        lines = [
            f"# Screen: {spec['name']}",
            f"**Components**: {spec['component_count']}  |  **Sections**: {spec['sections_count']}",
            "",
        ]

        if not spec["sections"] and not spec["components"]:
            gap_notice = ScreenStructureGap(spec.get("jsx_snippet", "")).notice(
                recoverable_via=spec["name"]
            )
            if gap_notice:
                lines.append(gap_notice)
                lines.append("")

        # ── Sections ──────────────────────────────────────────────────────────
        if spec["sections"]:
            lines.append("## Sections\n")
            for sec in spec["sections"]:
                lines.append(f"### {sec['name']}")
                lines.append(f"*Detection*: {sec['detection_method']}")
                if sec["component_refs"]:
                    lines.append(f"**Components**: {', '.join(sec['component_refs'])}")
                if sec["styles_by_element"]:
                    lines.append("**Styles**:")
                    lines.extend(_section_style_group_lines(
                        sec["styles_by_element"], recoverable_via=f'screen="{spec["name"]}", section="{sec["name"]}"',
                    ))
                if sec["texts"]:
                    for t in sec["texts"][:6]:
                        lines.append(f'- "{t}"')
                    notice = _truncation_notice(len(sec["texts"]), 6)
                    if notice:
                        lines.append(notice)
                if sec["jsx_snippet"]:
                    jsx = CappedJsx(sec["jsx_snippet"], 2000)
                    lines.append("\n```jsx")
                    lines.append(jsx)
                    lines.append("```")
                    notice = jsx.notice(recoverable_via=None)  # sections aren't Component nodes
                    if notice:
                        lines.append(notice)
                lines.append("")

        # ── Components ────────────────────────────────────────────────────────
        if spec["components"]:
            lines.append("---\n## Components\n")
            for comp in spec["components"]:
                cname = comp["name"]
                lines.append(f"### {cname}")
                lines.append(f"**Type**: {comp['comp_type']} | **Occurrences**: {comp['occurrence']}")
                trunc_notice = _truncated_fields_notice(comp.get("truncated_fields"), recoverable_via=cname)
                if trunc_notice:
                    lines.append(trunc_notice)
                if comp["children"]:
                    lines.append(f"**Children**: {', '.join(comp['children'])}")

                if comp["props"]:
                    lines.append("\n#### Props")
                    lines.extend(_props_table_lines(comp["props"]))

                any_styles = False
                for state in StyleState:
                    state_styles = _dedupe_styles_by_property(comp["styles_by_state"].get(state, []))
                    if state_styles:
                        any_styles = True
                        lines.append(f"\n#### Styles — {state}")
                        lines.append("| Property | Value |")
                        lines.append("|---|---|")
                        for s in state_styles[:12]:
                            lines.append(f"| {s['property']} | {s['value']} |")
                        notice = _truncation_notice(len(state_styles), 12)
                        if notice:
                            lines.append(notice)
                if not any_styles:
                    notice = StyleExtractionGap(comp["jsx_snippet"]).notice()
                    if notice:
                        lines.append(f"\n{notice}")

                if comp["tokens"]:
                    lines.append("\n#### Tokens")
                    lines.append("| Label | Value | Category |")
                    lines.append("|---|---|---|")
                    for t in comp["tokens"]:
                        lines.append(f"| {t['label']} | {t['value']} | {t['category']} |")

                if comp["interactions"]:
                    lines.append("\n#### Interactions")
                    for i in comp["interactions"]:
                        lines.append(
                            f"- **{i['trigger']}**: `{i['css_prop']}` "
                            f"`{i['from_val']}` → `{i['to_val']}` ({i['transition']})"
                        )

                if comp["texts"]:
                    lines.append("\n#### Texts")
                    for t in comp["texts"][:8]:
                        lines.append(f'- "{t["content"]}" ({t["text_type"]})')
                    notice = _truncation_notice(len(comp["texts"]), 8)
                    if notice:
                        lines.append(notice)

                if comp["jsx_snippet"]:
                    jsx = CappedJsx(comp["jsx_snippet"], 2500)
                    lines.append("\n```jsx")
                    lines.append(jsx)
                    lines.append("```")
                    notice = jsx.notice(recoverable_via=cname)
                    if notice:
                        lines.append(notice)
                lines.append("")

        logger.debug("tools: get_screen_full(%s) — rendered", spec["name"])
        return "\n".join(lines)

    def get_screen(self, reader: GraphReader, name: str) -> str:
        screen = reader.get_screen(name)
        if not screen:
            all_screens = [s["name"] for s in reader.list_screens()]
            return f"Tela '{name}' não encontrada. Disponíveis: {', '.join(all_screens)}"

        lines = [
            f"# Tela: {screen['name']}",
            f"Componentes: {screen['component_count']}  |  Seções: {screen['sections_count']}",
            "",
        ]
        for sec in screen.get("sections", []):
            comp_refs = json.loads(sec.get("sec.components_json") or sec.get("components_json", "[]"))
            lines.append(f"### {sec.get('sec.name') or sec.get('name', '')}")
            if comp_refs:
                lines.append(f"Componentes: {', '.join(comp_refs)}")
        if screen.get("components"):
            lines.append("\n## Todos os componentes")
            by_type: dict[str, list[str]] = {}
            for c in screen["components"]:
                by_type.setdefault(c.get("c.comp_type", "component"), []).append(c.get("c.name", ""))
            for t, names in sorted(by_type.items()):
                lines.append(f"**{t}**: {', '.join(names)}")
        return "\n".join(lines)

    def get_section(self, reader: GraphReader, screen: str, section: str) -> str:
        sec = reader.get_section(screen, section)
        if not sec:
            return f"Seção '{section}' não encontrada em '{screen}'."
        lines = [f"# Seção: {sec['name']}  (em {screen})", ""]
        if sec["styles_by_element"]:
            lines.append("## Estilos")
            lines.extend(_section_style_group_lines(
                sec["styles_by_element"], recoverable_via=f'screen="{screen}", section="{sec["name"]}"',
            ))
        if sec["component_refs"]:
            lines.append("\n## Componentes")
            for comp in sec["component_refs"]:
                lines.append(f"- **{comp}**")
        if sec["texts"]:
            lines.append("\n## Textos")
            for t in sec["texts"][:8]:
                lines.append(f'- "{t}"')
            notice = _truncation_notice(len(sec["texts"]), 8)
            if notice:
                lines.append(notice)
        if sec["jsx_snippet"]:
            jsx = CappedJsx(sec["jsx_snippet"], 3000)
            lines.append("\n## JSX\n```jsx")
            lines.append(jsx)
            lines.append("```")
            notice = jsx.notice(recoverable_via=None)  # sections aren't Component nodes
            if notice:
                lines.append(notice)
        return "\n".join(lines)

    def get_component(self, reader: GraphReader, name: str) -> str:
        comp = reader.get_component(name)
        if not comp:
            return f"Componente '{name}' não encontrado. Use search('{name}') para explorar."

        cname = comp.get("c.name", name)
        lines = [
            f"# Componente: {cname}",
            f"Tipo: **{comp.get('c.comp_type', '')}**  |  Ocorrências: {comp.get('c.occurrence', '')}",
            f"Usado em: {', '.join(comp.get('screens_using', [])) or 'não detectado'}",
        ]
        trunc_notice = _truncated_fields_notice(comp.get("c.truncated_fields"), recoverable_via=cname)
        if trunc_notice:
            lines.append(trunc_notice)
        if comp.get("c.jsx_snippet"):
            jsx = CappedJsx(comp["c.jsx_snippet"], 4000)
            lines += ["", "## JSX", "```jsx", jsx, "```"]
            notice = jsx.notice(recoverable_via=cname)
            if notice:
                lines.append(notice)
        if comp.get("styles"):
            lines.append("\n## Estilos")
            by_state: dict[str, list[str]] = {}
            for s in comp["styles"]:
                by_state.setdefault(s.get("s.state", "default"), []).append(
                    f"`{s.get('s.property')}`: `{s.get('s.value')}`"
                )
            for state in StyleState:
                if state in by_state:
                    lines.append(f"**{state}**: {' | '.join(by_state[state][:6])}")
        else:
            notice = StyleExtractionGap(comp.get("c.jsx_snippet", "")).notice()
            if notice:
                lines.append(f"\n{notice}")
        if comp.get("tokens"):
            lines.append("\n## Tokens de design")
            for t in comp["tokens"]:
                lines.append(f"- **{t.get('t.label')}** = `{t.get('t.value')}` ({t.get('t.category')})")
        if comp.get("children"):
            lines.append(f"\n## Componentes filhos\n{', '.join(comp['children'])}")
        return "\n".join(lines)

    def get_tokens(self, reader: GraphReader, category: str | None, screen: str | None = None) -> str:
        rows = reader.get_tokens(category, screen)
        if not rows:
            return (
                f"Nenhum token encontrado para a tela '{screen}'." if screen
                else "Nenhum token encontrado."
            )
        lines = [f"# Design Tokens — tela {screen}\n" if screen else "# Design Tokens\n"]
        by_cat: dict[str, list] = {}
        for r in rows:
            by_cat.setdefault(r.get("t.category", "?"), []).append(r)
        for cat, tokens in sorted(by_cat.items()):
            lines.append(f"## {cat}")
            for t in tokens:
                lines.append(f"- **{t.get('t.label')}**: `{t.get('t.value')}` ({t.get('t.usage')} usos)")
            lines.append("")
        return "\n".join(lines)

    def find_token_usage(self, reader: GraphReader, value: str) -> str:
        usages = reader.find_token_usage(value)
        if not usages:
            return f"Token '{value}' não encontrado."
        lines = [f"# Uso do token: `{value}`\n"]
        for u in usages:
            lines.append(f"## {u.get('t.label')} = `{u.get('t.value')}` ({u.get('t.category')})")
            if u.get("components"):
                comps = ", ".join(c.get("c.name", "") for c in u["components"])
                lines.append(f"Componentes: {comps}")
            if u.get("screens"):
                lines.append(f"Telas: {', '.join(u['screens'])}")
            lines.append("")
        return "\n".join(lines)

    def tool_search(self, query: str) -> str:
        results = search(self._readers, query)
        if not results:
            return f"Nenhum resultado para '{query}'."
        shown = results[:30]
        lines = [f"# Resultados para: '{query}'\n"]
        if all(r.word_coverage < 1.0 for r in shown):
            lines.append(
                "> Nenhum resultado cobre todas as palavras da busca — os itens "
                "abaixo são correspondências **parciais** (compartilham só parte "
                "dos termos), não confirmam que a frase completa existe no "
                "protótipo.\n"
            )
        by_type: dict[str, list] = {}
        for r in shown:
            by_type.setdefault(r.type, []).append(r)
        for t, items in sorted(by_type.items()):
            lines.append(f"## {t}")
            for item in items:
                doc_tag = f" `[{item.doc}]`" if len(self._readers) > 1 else ""
                detail  = f" — {item.detail}" if item.detail else ""
                partial_tag = " *(parcial)*" if item.word_coverage < 1.0 else ""
                lines.append(f"- **{item.name}**{doc_tag}{detail}{partial_tag}")
            lines.append("")
        return "\n".join(lines)

    def impact(self, reader: GraphReader, name: str) -> str:
        result = reader.get_impact(name)
        if not result.get("found"):
            return f"'{name}' não encontrado. Use search() para localizar."
        lines = [f"# Análise de impacto: {name}\n"]
        if "type" in result:
            lines.append(f"Tipo: **{result['type']}**")
            lines.append(f"\n## Telas afetadas ({len(result.get('screens', []))})")
            for s in result.get("screens", []):
                lines.append(f"- {s}")
        elif "label" in result:
            lines.append(f"Token: **{result['label']}** = `{result['value']}`")
            lines.append(f"\n## Componentes que usam este token ({len(result.get('components', []))})")
            for c in result.get("components", []):
                lines.append(f"- {c}")
        return "\n".join(lines)

    def get_full_styles(self, reader: GraphReader, name: str, screen: str, section: str) -> str:
        """
        Uncapped style list — the get_full_jsx equivalent for styles.

        The reader already returns every style row; get_section/
        get_screen_full/get_component_spec only ever slice it for display
        ("+N mais" with no way back). This renders the same reader data
        without the slice — no new query, just no truncation (see
        docs/changes/C36).
        """
        if screen and section:
            sec = reader.get_section(screen, section)
            if not sec:
                return f"Seção '{section}' não encontrada em '{screen}'."
            if not sec["styles_by_element"]:
                return f"Nenhum estilo encontrado para a seção '{sec['name']}'."
            lines = [f"# Estilos completos: {sec['name']} (em {screen})\n"]
            for selector, raw_styles in sorted(sec["styles_by_element"].items()):
                lines.append(f"## {selector}")
                lines.append("| Propriedade | Valor |")
                lines.append("|---|---|")
                for s in _dedupe_styles_by_property(raw_styles):
                    lines.append(f"| {s['property']} | {s['value']} |")
                lines.append("")
            return "\n".join(lines)

        if name:
            spec = reader.get_component_spec(name)
            if not spec:
                return f"Componente '{name}' não encontrado. Use search('{name}') para explorar."
            if not spec.get("styles_by_state"):
                return f"Nenhum estilo encontrado para o componente '{spec['c.name']}'."
            lines = [f"# Estilos completos: {spec['c.name']}\n"]
            for state, raw_styles in sorted(spec["styles_by_state"].items()):
                lines.append(f"## Estado: {state}")
                lines.append("| Propriedade | Valor |")
                lines.append("|---|---|")
                for s in _dedupe_styles_by_property(raw_styles):
                    lines.append(f"| {s['property']} | {s['value']} |")
                lines.append("")
            return "\n".join(lines)

        return "Informe `name` (componente) ou `screen` + `section` (seção)."

    def get_full_jsx(self, reader: GraphReader, name: str) -> str:
        raw = reader.get_full_jsx(name)
        if not raw:
            return f"JSX completo não disponível para '{name}'. Rode: design-graph --force <proto.html>"

        jsx = JsxSnippet(raw)
        if jsx.was_sanitized:
            header = f"# JSX de {name} (sanitizado na extração — não é o fonte original)"
            footer = (
                "\n> Este snippet já passou por `sanitize_jsx` na extração — "
                "handlers longos e ramos de lista/condicional/ternária foram "
                "substituídos por marcadores. Chamar `get_full_jsx` de novo não "
                "recupera o restante: o texto original não fica armazenado."
            )
        else:
            header = f"# JSX completo: {name}"
            footer = ""
        return f"{header}\n\n```jsx\n{jsx}\n```{footer}"

    def get_component_interactions(self, reader: GraphReader, name: str) -> str:
        interactions = reader.get_interactions(name)
        if not interactions:
            return f"Nenhuma interação detectada para '{name}'."
        lines = [f"# Interações: {name}\n"]
        for i in interactions:
            lines.append(f"**{i.get('i.trigger', '').upper()}**")
            lines.append(f"  Propriedade: `{i.get('i.css_prop')}`")
            if i.get("i.from_val"):
                lines.append(f"  De: `{i['i.from_val']}`")
            lines.append(f"  Para: `{i.get('i.to_val')}`")
            if i.get("i.transition"):
                lines.append(f"  Transition: `{i['i.transition']}`")
            lines.append("")
        return "\n".join(lines)

    def get_component_children(self, reader: GraphReader, name: str) -> str:
        children = reader.get_component_children(name)
        if not children:
            if not reader.component_exists(name):
                return f"'{name}' não encontrado. Use search() para localizar."
            return f"'{name}' é um componente folha — não possui filhos detectados."
        lines = [f"# Filhos de: {name}\n"]
        for child in children:
            lines.append(f"- `{child}`")
        return "\n".join(lines)

    def list_components(self, reader: GraphReader, comp_type: str | None, limit: int | None = None) -> str:
        comps = reader.list_components(comp_type)
        if not comps:
            if comp_type:
                return f"Nenhum componente encontrado para o tipo '{comp_type}'."
            return "Nenhum componente encontrado."

        # Unlike every other listing tool (search, get_screen_full,
        # get_component_spec), this had no cap at all — a prototype with
        # hundreds of components returned every row in one response,
        # against the product's own point of reducing tokens in the
        # agent's context. Already sorted by occurrence DESC (reader.list_components),
        # so the shown slice is the most-used components, not an arbitrary cut.
        effective_limit = limit if limit and limit > 0 else _DEFAULT_LIST_COMPONENTS_LIMIT
        shown = comps[:effective_limit]

        header = f"## Componentes — tipo: {comp_type}" if comp_type else "## Componentes"
        lines = [header, f"({len(comps)} encontrados)\n",
                 "| Nome | Tipo | Ocorrências |",
                 "|------|------|-------------|"]
        for c in shown:
            lines.append(f"| {c['c.name']} | {c['c.comp_type']} | {c['c.occurrence']} |")
        notice = _truncation_notice(len(comps), len(shown))
        if notice:
            lines.append(notice + " (passe limit= para ver mais, ou comp_type= para filtrar)")
        logger.debug("tools: list_components(type=%s) → %d/%d rows shown", comp_type, len(shown), len(comps))
        return "\n".join(lines)

    def _render_shared_css_class_spec(
        self, reader: GraphReader, class_name: str, styles: list[dict],
    ) -> str:
        """
        Render a CSS class that was never factored into a named React
        component (e.g. `.page-title`, `.chip`, `.audit-dot` — shared by
        several screens' own inline markup) as a spec, clearly labeled as a
        class rather than a component so it's never mistaken for one (see
        docs/changes/C36 P3).
        """
        owners = reader.find_class_owners(class_name)
        lines = [
            f"# Spec: .{class_name}",
            "**Tipo**: classe CSS (não é um componente React nomeado)",
        ]
        used_in = [*owners["components"], *(f'{o["screen"]} / {o["section"]}' for o in owners["sections"])]
        if used_in:
            lines.append(f"**Usado em**: {', '.join(used_in)}")
        lines.append("\n## Estilos")
        lines.append("| Propriedade | Valor |")
        lines.append("|---|---|")
        for s in styles:
            lines.append(f"| {s['property']} | {s['value']} |")
        return "\n".join(lines)

    def get_component_spec(self, reader: GraphReader, name: str) -> str:
        spec = reader.get_component_spec(name)
        if not spec:
            class_styles = reader.find_styles_by_class(name)
            if class_styles:
                return self._render_shared_css_class_spec(reader, name, class_styles)
            return f"Componente '{name}' não encontrado. Use search('{name}') para explorar."

        cname = spec["c.name"]
        lines = [
            f"# Spec: {cname}",
            f"**Tipo**: {spec['c.comp_type']} | **Ocorrências**: {spec['c.occurrence']}",
        ]
        if spec.get("screens_using"):
            lines.append(f"**Telas**: {', '.join(spec['screens_using'])}")
        trunc_notice = _truncated_fields_notice(spec.get("c.truncated_fields"), recoverable_via=cname)
        if trunc_notice:
            lines.append(trunc_notice)
        if spec.get("parents") or spec.get("children"):
            lines.append("\n## Hierarquia")
            if spec["parents"]:
                lines.append(f"- Pais: {', '.join(spec['parents'])}")
            if spec["children"]:
                lines.append(f"- Filhos: {', '.join(spec['children'])}")
        if spec.get("styles_by_state"):
            for state, raw_styles in sorted(spec["styles_by_state"].items()):
                styles = _dedupe_styles_by_property(raw_styles)
                lines.append(f"\n## Estilos — {state}")
                lines.append("| Propriedade | Valor |")
                lines.append("|---|---|")
                for s in styles[:12]:
                    lines.append(f"| {s['property']} | {s['value']} |")
                notice = _truncation_notice(len(styles), 12)
                if notice:
                    lines.append(notice)
        else:
            notice = StyleExtractionGap(spec.get("c.jsx_snippet", "")).notice()
            if notice:
                lines.append(f"\n{notice}")
        if spec.get("responsive_styles_by_media"):
            lines.append("\n## Estilos responsivos")
            lines.append(
                "Valores abaixo só se aplicam sob a condição `@media` indicada — "
                "não confundir com o valor default acima."
            )
            for media, raw_styles in spec["responsive_styles_by_media"].items():
                styles = _dedupe_styles_by_property(raw_styles)
                lines.append(f"\n**`@media {media}`**")
                lines.append("| Propriedade | Valor |")
                lines.append("|---|---|")
                for s in styles[:12]:
                    lines.append(f"| {s['property']} | {s['value']} |")
                notice = _truncation_notice(len(styles), 12)
                if notice:
                    lines.append(notice)
        if spec.get("tokens"):
            lines.append("\n## Tokens")
            lines.append("| Label | Valor | Categoria |")
            lines.append("|---|---|---|")
            for t in spec["tokens"]:
                lines.append(f"| {t.get('t.label')} | {t.get('t.value')} | {t.get('t.category')} |")
        if spec.get("texts"):
            lines.append("\n## Textos")
            for t in spec["texts"][:8]:
                lines.append(f'- "{t.get("t.content")}" ({t.get("t.text_type")})')
            notice = _truncation_notice(len(spec["texts"]), 8)
            if notice:
                lines.append(notice)
        if spec.get("interactions"):
            lines.append("\n## Interações")
            for i in spec["interactions"]:
                lines.append(
                    f"- {i.get('i.trigger')}: {i.get('i.css_prop')} "
                    f"`{i.get('i.from_val')}` → `{i.get('i.to_val')}` ({i.get('i.transition')})"
                )
        if spec.get("props"):
            lines.append("\n## Props")
            lines.extend(_props_table_lines(spec["props"]))
        if spec.get("c.jsx_snippet"):
            jsx = CappedJsx(spec["c.jsx_snippet"], 3000)
            lines.append("\n## JSX\n```jsx")
            lines.append(jsx)
            lines.append("```")
            notice = jsx.notice(recoverable_via=cname)
            if notice:
                lines.append(notice)
        logger.debug("tools: get_component_spec(%s) — rendered", cname)
        return "\n".join(lines)

    def get_component_full(self, reader: GraphReader, name: str) -> str:
        """
        Render the root component plus every descendant (via CONTAINS, up
        to 3 levels) as Markdown — one call to reconstruct a complex
        component instead of cascading get_component_children per level.
        """
        full = reader.get_component_full(name)
        if not full:
            return f"Componente '{name}' não encontrado. Use search('{name}') para explorar."

        root_name = full["root"]
        lines = [
            f"# Árvore de componente: {root_name}",
            f"**Componentes na árvore**: {len(full['components'])}\n",
        ]
        for comp in full["components"]:
            cname = comp["name"]
            marker = " (raiz)" if cname == root_name else ""
            lines.append(f"## {cname}{marker}")
            lines.append(f"**Tipo**: {comp['comp_type']} | **Ocorrências**: {comp['occurrence']}")
            trunc_notice = _truncated_fields_notice(comp.get("truncated_fields"), recoverable_via=cname)
            if trunc_notice:
                lines.append(trunc_notice)
            if comp["children"]:
                lines.append(f"**Filhos**: {', '.join(comp['children'])}")

            if comp["props"]:
                lines.append("\n#### Props")
                lines.extend(_props_table_lines(comp["props"]))

            any_styles = False
            for state, raw_styles in sorted(comp["styles_by_state"].items()):
                styles = _dedupe_styles_by_property(raw_styles)
                if styles:
                    any_styles = True
                    lines.append(f"\n#### Estilos — {state}")
                    lines.append("| Propriedade | Valor |")
                    lines.append("|---|---|")
                    for s in styles[:12]:
                        lines.append(f"| {s['property']} | {s['value']} |")
                    notice = _truncation_notice(len(styles), 12)
                    if notice:
                        lines.append(notice)
            if not any_styles:
                notice = StyleExtractionGap(comp["jsx_snippet"]).notice()
                if notice:
                    lines.append(f"\n{notice}")

            if comp["tokens"]:
                lines.append("\n#### Tokens")
                for t in comp["tokens"]:
                    lines.append(f"- **{t['label']}** = `{t['value']}` ({t['category']})")

            if comp["interactions"]:
                lines.append("\n#### Interações")
                for i in comp["interactions"]:
                    lines.append(
                        f"- **{i['trigger']}**: `{i['css_prop']}` "
                        f"`{i['from_val']}` → `{i['to_val']}` ({i['transition']})"
                    )

            if comp["texts"]:
                lines.append("\n#### Textos")
                for t in comp["texts"][:8]:
                    lines.append(f'- "{t["content"]}" ({t["text_type"]})')
                notice = _truncation_notice(len(comp["texts"]), 8)
                if notice:
                    lines.append(notice)

            if comp["jsx_snippet"]:
                jsx = CappedJsx(comp["jsx_snippet"], 2500)
                lines.append("\n```jsx")
                lines.append(jsx)
                lines.append("```")
                notice = jsx.notice(recoverable_via=cname)
                if notice:
                    lines.append(notice)
            lines.append("")

        logger.debug("tools: get_component_full(%s) — %d components", root_name, len(full["components"]))
        return "\n".join(lines)

    def get_build_diff(self, reader: GraphReader) -> str:
        diff = reader.get_build_diff()
        if diff is None:
            return (
                "Nenhum diff de build disponível para este documento "
                "(protótipo carregado sem state.json associado, ou nunca reconstruído)."
            )
        if diff.get("is_first_build"):
            return "Primeira build deste protótipo — não há build anterior para comparar."

        screens_added   = diff.get("screens_added", [])
        screens_removed = diff.get("screens_removed", [])
        comps_added     = diff.get("comps_added", [])
        comps_removed   = diff.get("comps_removed", [])
        if not any((screens_added, screens_removed, comps_added, comps_removed)):
            return "Nenhuma mudança de telas ou componentes desde a build anterior."

        lines = ["# Diff da última build\n"]
        if screens_added:
            lines.append(f"**Telas adicionadas**: {', '.join(screens_added)}")
        if screens_removed:
            lines.append(f"**Telas removidas**: {', '.join(screens_removed)}")
        if comps_added:
            lines.append(f"**Componentes adicionados**: {', '.join(comps_added)}")
        if comps_removed:
            lines.append(f"**Componentes removidos**: {', '.join(comps_removed)}")
        return "\n".join(lines)

    def validate_component_implementation(
        self, reader: GraphReader, name: str, jsx_source: str,
    ) -> str:
        if not jsx_source.strip():
            return "jsx_source vazio — nada para comparar."
        if len(jsx_source) > _MAX_VALIDATION_JSX_SOURCE_CHARS:
            return (
                f"jsx_source muito grande ({len(jsx_source)} caracteres, limite "
                f"{_MAX_VALIDATION_JSX_SOURCE_CHARS}). Passe só a expressão JSX do "
                f"componente, não o arquivo inteiro."
            )

        spec = reader.get_component_spec(name)
        if not spec:
            return f"Componente '{name}' não encontrado. Use search('{name}') para explorar."
        cname = spec["c.name"]

        candidate = _extract_validation_candidate(jsx_source)
        if candidate is None:
            return (
                "Não foi possível interpretar jsx_source como JSX válido "
                "(passe a expressão JSX, ex.: o que get_full_jsx devolve, não uma "
                "declaração de função completa)."
            )

        lines = [
            f"# Validação: {cname}",
            "> Best-effort: não verifica estilos vindos de classes CSS do protótipo "
            "nem cores Tailwind (ex. bg-blue-500) — só estilos inline e utilitários "
            "de layout têm cobertura confiável aqui. Um relatório limpo não é prova "
            "de correspondência pixel-perfeita.\n",
        ]

        stored_children = set(spec.get("children", []))
        candidate_children = set(candidate.child_refs)
        missing_children = sorted(stored_children - candidate_children)
        extra_children = sorted(candidate_children - stored_children)
        if missing_children:
            lines.append(f"⚠ **Filhos ausentes na implementação**: {', '.join(missing_children)}")
        if extra_children:
            lines.append(f"ℹ **Filhos novos (não estavam na spec original)**: {', '.join(extra_children)}")
        if not missing_children and not extra_children and stored_children:
            lines.append("✅ Filhos batem com a spec.")

        stored_default = {
            (s["property"], s["value"])
            for s in spec.get("styles_by_state", {}).get("default", [])
        }
        candidate_default = {
            (s.property, s.value) for s in candidate.styles if s.state == StyleState.DEFAULT
        }
        missing_styles = sorted(stored_default - candidate_default)
        if missing_styles:
            lines.append("\n⚠ **Estilos default ausentes na implementação** (property, value):")
            for prop, val in missing_styles[:15]:
                lines.append(f"- `{prop}`: `{val}`")
            notice = _truncation_notice(len(missing_styles), 15)
            if notice:
                lines.append(notice)
        elif stored_default:
            lines.append("\n✅ Estilos default inline batem com a spec (dentro do que é verificável).")

        stored_texts = {t["t.content"] for t in spec.get("texts", [])}
        candidate_texts = {t.content for t in candidate.texts}
        missing_texts = sorted(stored_texts - candidate_texts)
        if missing_texts:
            lines.append("\n⚠ **Textos ausentes na implementação**:")
            for t in missing_texts[:10]:
                lines.append(f'- "{t}"')
            notice = _truncation_notice(len(missing_texts), 10)
            if notice:
                lines.append(notice)
        elif stored_texts:
            lines.append("\n✅ Textos batem com a spec.")

        logger.debug("tools: validate_component_implementation(%s) — rendered", cname)
        return "\n".join(lines)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _find_reader(self, name: str) -> GraphReader | None:
        try:
            GraphDocumentName(name)
        except ValueError:
            # Malformed doc name (empty, "..", contains "/" or "\\") — same
            # validation already applied to CLI --doc, reused here for
            # defense in depth even though nothing today reconstructs a
            # Path from this value. Falls through to the normal "not found"
            # message rather than a raw ValueError.
            return None
        for doc_name, reader in self._readers:
            if doc_name.lower() == name.lower():
                return reader
        for doc_name, reader in self._readers:
            if name.lower() in doc_name.lower():
                return reader
        return None
