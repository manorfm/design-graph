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

from design_graph.graph.reader import GraphReader
from design_graph.mcp.search import search

logger = logging.getLogger(__name__)

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
            "Returns a screen's full composition: sections, components, texts and styles. "
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
            "Returns design tokens (colors and spacing). "
            "Always call before writing any color or spacing value."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "'color' or 'spacing'. Omit for all tokens.",
                    "enum": ["color", "spacing"],
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
        "description": "Returns the full unsanitized JSX of a component. Use when get_component truncated details.",
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
            "get_screen":                lambda: self.get_screen(reader, name),
            "get_section":               lambda: self.get_section(reader, args.get("screen", ""), args.get("section", "")),
            "get_component":             lambda: self.get_component(reader, name),
            "get_tokens":                lambda: self.get_tokens(reader, args.get("category")),
            "find_token_usage":          lambda: self.find_token_usage(reader, args.get("value", "")),
            "impact":                    lambda: self.impact(reader, name),
            "get_full_jsx":              lambda: self.get_full_jsx(reader, name),
            "get_component_interactions": lambda: self.get_component_interactions(reader, name),
            "get_component_children":    lambda: self.get_component_children(reader, name),
        }

        fn = dispatch_map.get(tool_name)
        if not fn:
            available = ", ".join(dispatch_map.keys())
            return f"Unknown tool: {tool_name}. Available: {available}"

        return fn()

    # ── Tool methods ──────────────────────────────────────────────────────────

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
        if sec["styles"]:
            lines.append("## Estilos")
            for prop, val in list(sec["styles"].items())[:6]:
                lines.append(f"- `{prop}`: `{val}`")
        if sec["component_refs"]:
            lines.append("\n## Componentes")
            for comp in sec["component_refs"]:
                lines.append(f"- **{comp}**")
        if sec["texts"]:
            lines.append("\n## Textos")
            for t in sec["texts"][:8]:
                lines.append(f'- "{t}"')
        if sec["jsx_snippet"]:
            lines.append("\n## JSX\n```jsx")
            lines.append(sec["jsx_snippet"][:3000])
            lines.append("```")
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
        if comp.get("c.jsx_snippet"):
            lines += ["", "## JSX", "```jsx", comp["c.jsx_snippet"][:4000], "```"]
        if comp.get("styles"):
            lines.append("\n## Estilos")
            by_state: dict[str, list[str]] = {}
            for s in comp["styles"]:
                by_state.setdefault(s.get("s.state", "default"), []).append(
                    f"`{s.get('s.property')}`: `{s.get('s.value')}`"
                )
            for state in ("default", "hover", "focus", "transition"):
                if state in by_state:
                    lines.append(f"**{state}**: {' | '.join(by_state[state][:6])}")
        if comp.get("tokens"):
            lines.append("\n## Tokens de design")
            for t in comp["tokens"]:
                lines.append(f"- **{t.get('t.label')}** = `{t.get('t.value')}` ({t.get('t.category')})")
        if comp.get("children"):
            lines.append(f"\n## Componentes filhos\n{', '.join(comp['children'])}")
        return "\n".join(lines)

    def get_tokens(self, reader: GraphReader, category: str | None) -> str:
        rows = reader.get_tokens(category)
        if not rows:
            return "Nenhum token encontrado."
        lines = ["# Design Tokens\n"]
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
        lines = [f"# Resultados para: '{query}'\n"]
        by_type: dict[str, list] = {}
        for r in results[:30]:
            by_type.setdefault(r.type, []).append(r)
        for t, items in sorted(by_type.items()):
            lines.append(f"## {t}")
            for item in items:
                doc_tag = f" `[{item.doc}]`" if len(self._readers) > 1 else ""
                detail  = f" — {item.detail}" if item.detail else ""
                lines.append(f"- **{item.name}**{doc_tag}{detail}")
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

    def get_full_jsx(self, reader: GraphReader, name: str) -> str:
        jsx = reader.get_full_jsx(name)
        if not jsx:
            return f"JSX completo não disponível para '{name}'. Rode: design-graph --force <proto.html>"
        return f"# JSX completo: {name}\n\n```jsx\n{jsx}\n```"

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
            return f"'{name}' não possui filhos detectados (componente folha ou não encontrado)."
        lines = [f"# Filhos de: {name}\n"]
        for child in children:
            lines.append(f"- `{child}`")
        return "\n".join(lines)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _find_reader(self, name: str) -> GraphReader | None:
        for doc_name, reader in self._readers:
            if doc_name.lower() == name.lower():
                return reader
        for doc_name, reader in self._readers:
            if name.lower() in doc_name.lower():
                return reader
        return None
