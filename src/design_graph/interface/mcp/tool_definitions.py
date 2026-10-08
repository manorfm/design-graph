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
                "mode": {
                    "type": "string",
                    "description": (
                        "Mode (e.g. a light or dark theme name) to keep: that mode's values plus "
                        "tokens shared by every mode. Omit for every mode; tokens with a mode show it "
                        "in brackets."
                    ),
                },
                "doc": _doc_param(),
            },
            "required": [],
        },
    },
    {
        "name": "search",
        "description": (
            "Where is X? Searches screens, components (by name and type), sections, props, texts, the copy "
            "components' lists hold (option and tab labels), tokens, "
            "shared CSS classes and the names the code uses (handlers, state) in all prototypes; texts say "
            "their screen › section. Matches the query as a whole: when only some of its words appear apart, "
            "it answers that it does not exist in the prototype and lists the closest things it does have — "
            "so stop looking for screens or dialogs that were never designed. Portuguese terms work too "
            "(botão, modal, tabela, seção)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search term (PT or EN)"}},
            "required": ["query"],
        },
    },
    {
        "name": "impact",
        "description": (
            "Who uses X, and what a change to it would reach: a component or screen (the screens affected), a "
            "token by name (the components using it), or a literal value such as #FFB81C (the tokens holding it, "
            "and the components and screens using them)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Component, screen, token name, or a literal value"},
                "doc":  _doc_param(),
            },
            "required": ["name"],
        },
    },
    {
        "name": "assemble_page",
        "description": (
            "Everything needed to build one screen, in one call and in a fixed order: header (viewport, "
            "modes, navigation, components), the screen's own skeleton, each component it renders once, "
            "the data they repeat, the tokens it uses by mode, and the libraries and fonts to install. "
            "Pass known=[names] with the components you already received for another screen to leave "
            "their definitions out. A long answer comes in parts (part=N); nothing is cut."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Screen name"},
                "known": {"type": "array", "items": {"type": "string"},
                          "description": "Components you already have — their definitions are left out"},
                "part": {"type": "integer", "minimum": 1, "description": "Part of a long answer (default 1)"},
                "doc": _doc_param(),
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_screen",
        "description": (
            "One screen, to inspect it (to build it, use assemble_page). detail=outline (default): its sections "
            "and the components it uses, by name, plus navigation and variants. detail=full: every section with "
            "its styles and texts and every component it renders, whole. detail=layout: the display/flex/grid and "
            "size profile of each component and section. section=<name>: that section alone — styles by selector, "
            "texts, components and source. compare=<other screen>: the components, texts and style declarations "
            "only one of the two has — what a variant (desktop × mobile, light × dark) changes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Screen name (fuzzy match)"},
                "section": {"type": "string", "description": "Only this section of the screen"},
                "detail": {"type": "string", "enum": ["outline", "full", "layout"], "description": "How much (default outline)"},
                "compare": {"type": "string", "description": "Another screen to tell this one apart from (fuzzy match)"},
                "doc": _doc_param(),
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_component",
        "description": (
            "One component, whole: hierarchy (parents, children, screens using it), styles by state (default, "
            "hover, focus, responsive), tokens by mode, texts, interactions, props with defaults, referenced data "
            "and its source. depth=1..3 also returns the components it nests, that many levels down — a modal, "
            "form or card with everything inside it in one call. A screen's name is answered as that screen."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Component name (fuzzy match)"},
                "depth": {"type": "integer", "minimum": 0, "maximum": 3,
                          "description": "0: only this component (default); 1-3: plus its nested components"},
                "doc": _doc_param(),
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_full",
        "description": (
            "Returns, whole, what another answer shortened — every '+N mais' or cut notice names the exact call. "
            "aspect=source: a component's or screen's source as the prototype wrote it, in parts for long ones "
            "(part=N). aspect=styles / aspect=texts: the complete style or text list of a component (name=) or of "
            "a screen section (screen= and section=). aspect=data: a component's referenced module data (e.g. an "
            "icon-name → SVG-path table) — reuse those exact values."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "aspect": {"type": "string", "enum": ["source", "styles", "texts", "data"]},
                "name": {"type": "string", "description": "Component or screen name"},
                "screen": {"type": "string", "description": "Screen of the section (styles/texts of a section)"},
                "section": {"type": "string", "description": "Section name (styles/texts of a section)"},
                "part": {"type": "integer", "minimum": 1, "description": "Part of a long source (default 1)"},
                "doc": _doc_param(),
            },
            "required": ["aspect"],
        },
    },
    {
        "name": "get_asset",
        "description": (
            "Writes the files of one font family or image the prototype embeds into the workspace, under "
            "design-graph-assets/<name>/, and returns their paths — use it instead of recreating an icon or "
            "guessing a font file. Names come from get_resources."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Resource name, as get_resources lists it"},
                "doc": _doc_param(),
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_resources",
        "description": (
            "Lists what the prototype loads besides its own markup: libraries with their version and "
            "origin (declare them in the project, never copy their code), fonts with weights, styles, "
            "subsets and where they likely come from, images, the design tool's runtime (never "
            "reproduce it) and the prototype's own code modules. Pass screen to list only what that "
            "screen loads. Binaries are described, never returned."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["library", "runtime", "module", "font", "image"],
                         "description": "Only resources of this kind"},
                "screen": {"type": "string", "description": "Only what this screen loads"},
                "doc": _doc_param(),
            },
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
            "Compares an implementation you wrote against a component's stored spec (children, "
            "default-state styles, texts) and reports discrepancies. The source is read by the same "
            "capture that built this prototype, in the same format get_full(aspect=source) returns. Best-effort, "
            "not a full re-extraction: it reliably catches missing/extra child components and missing "
            "inline styles/texts, but CANNOT verify styles that came from the prototype's own "
            "stylesheet classes or utility classes (e.g. bg-blue-500), which a standalone fragment "
            "doesn't carry. Treat a clean report as 'no red flags found', not proof of a pixel-perfect "
            f"match. Keep source under {MAX_VALIDATION_SOURCE_CHARS} characters."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Component name to compare against (partial name accepted)"},
                "source": {"type": "string", "description": "The component source you implemented, e.g. '<button style={{color: \"red\"}}>OK</button>'"},
                "doc": _doc_param(),
            },
            "required": ["name", "source"],
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
