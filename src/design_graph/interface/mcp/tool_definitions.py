"""The MCP tool catalogue: names, descriptions and input schemas."""

from __future__ import annotations

from design_graph.model.entities import ComponentType, TokenCategory
from design_graph.interface.mcp.build_tools import DEFAULT_METRICS_LIMIT
from design_graph.interface.mcp.component_tools import DEFAULT_LIST_COMPONENTS_LIMIT
from design_graph.interface.mcp.validation_tool import MAX_VALIDATION_SOURCE_CHARS


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
        "name": "get_full_texts",
        "description": "Returns a component's, screen's, or screen section's complete text list, without the display cap other tools apply ('+N mais'). Pass name= for a component or screen, or screen= + section= for one section. Exact names are resolved before partial matches; ambiguous partial names return their candidates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name":    {"type": "string", "description": "Component or screen name (mutually exclusive with screen/section)"},
                "screen":  {"type": "string", "description": "Screen name (use together with section)"},
                "section": {"type": "string", "description": "Section name or partial name (use together with screen)"},
                "doc":     _doc_param(),
            },
        },
    },
    {
        "name": "get_component_data",
        "description": "Returns the complete, uncapped content of every module-level constant a component's own body references by name (e.g. an icon-name -> SVG-path lookup table indexed as ICONS[name], or a role-key -> badge metadata table) — the exact same data the prototype itself renders from, not a substitute. Use this before inventing an icon/asset for a component whose spec showed a 'Dados referenciados' section, or when that section was truncated ('+N mais').",
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
            f"Response is capped at {DEFAULT_LIST_COMPONENTS_LIMIT} rows by default (most-used "
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
                    "description": f"Max rows to return. Default {DEFAULT_LIST_COMPONENTS_LIMIT}.",
                },
                "doc": _doc_param(),
            },
            "required": [],
        },
    },
    {
        "name": "get_metrics",
        "description": (
            "Returns usage metrics for this server's own tool calls: counts by tool and "
            "outcome, not-found/ambiguous/no-results rate, per-prototype breakdown, and the "
            "search queries that most often returned nothing. Filter by doc, tool, outcome "
            "or time window. Default output is an aggregate summary; pass raw=true for the "
            "underlying call list instead."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "doc": {
                    "type": "string",
                    "description": "Filter to calls tagged with this prototype. Omit to include every prototype.",
                },
                "tool": {
                    "type": "string",
                    "description": "Filter to calls of one tool (e.g. 'search').",
                },
                "outcome": {
                    "type": "string",
                    "description": "Filter by outcome: ok|not_found|ambiguous|no_results|error.",
                },
                "since": {
                    "type": "string",
                    "description": "Lower bound: ISO-8601 timestamp or relative shorthand ('24h', '7d', '30m').",
                },
                "until": {
                    "type": "string",
                    "description": "Upper bound: ISO-8601 timestamp or relative shorthand.",
                },
                "limit": {
                    "type": "integer",
                    "description": f"Max raw records shown when raw=true. Default {DEFAULT_METRICS_LIMIT}. Does not affect the aggregate.",
                },
                "raw": {
                    "type": "boolean",
                    "description": "Return the raw call list instead of the aggregate summary.",
                },
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
            f"a full function declaration, and under {MAX_VALIDATION_SOURCE_CHARS} characters."
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
            "Set the active prototype for this MCP connection. "
            "All subsequent calls without doc= will use this prototype. "
            "The selection lives on the server connection, not the task: it resets "
            "whenever the MCP connection restarts (e.g. a '/mcp' reconnect), even mid-task. "
            "If 'Multiple prototypes loaded...' reappears after already selecting one, "
            "call this again rather than assuming the earlier call still holds. "
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
