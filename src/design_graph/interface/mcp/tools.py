"""
MCP tool dispatch.

Each tool lives in a module grouped by what it is about (screens, components,
full sources, discovery, builds, validation) and returns Markdown. This
module only decides which prototype a call is about and routes it.

ToolDispatcher.pick_reader() resolves which prototype to use:
  Priority: explicit doc= argument → session active_doc → auto-select → error
"""

from __future__ import annotations

from design_graph.interface.mcp import (
    build_tools,
    component_tools,
    discovery_tools,
    full_tools,
    screen_tools,
    validation_tool,
)
from design_graph.model.graph.catalog import GraphDocumentName
from design_graph.model.graph.reader import GraphReader


class ToolDispatcher:
    """Resolves the prototype a tool call is about and routes the call to its tool."""

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
        """Route a tool call to its tool."""
        doc  = args.get("doc")
        name = args.get("name", "")

        if tool_name == "list_screens":
            return screen_tools.list_screens(self._readers)

        if tool_name == "search":
            return discovery_tools.tool_search(self._readers, args.get("query", ""))

        if tool_name == "get_metrics":
            return build_tools.get_metrics(
                doc=doc, tool=args.get("tool"), outcome=args.get("outcome"),
                since=args.get("since"), until=args.get("until"),
                limit=args.get("limit"), raw=bool(args.get("raw", False)),
            )

        reader, err = self.pick_reader(doc, active_doc)
        if err:
            return err

        screen, section = args.get("screen", ""), args.get("section", "")
        dispatch_map = {
            "get_component_props":       lambda: component_tools.get_component_props(reader, name),
            "get_screen_layout":         lambda: screen_tools.get_screen_layout(reader, name),
            "get_screen_full":           lambda: screen_tools.get_screen_full(reader, name),
            "get_screen":                lambda: screen_tools.get_screen(reader, name),
            "get_section":               lambda: screen_tools.get_section(reader, screen, section),
            "get_component":             lambda: component_tools.get_component(reader, name),
            "get_tokens":                lambda: discovery_tools.get_tokens(
                reader, args.get("category"), args.get("screen"), args.get("mode"),
            ),
            "find_token_usage":          lambda: discovery_tools.find_token_usage(reader, args.get("value", "")),
            "get_resources":             lambda: discovery_tools.get_resources(reader, args.get("kind"), args.get("screen")),
            "impact":                    lambda: discovery_tools.impact(reader, name),
            "get_full_source":           lambda: full_tools.get_full_source(reader, name, args.get("part", 1)),
            "get_full_styles":           lambda: full_tools.get_full_styles(reader, name, screen, section),
            "get_full_texts":            lambda: full_tools.get_full_texts(reader, name, screen, section),
            "get_component_data":        lambda: component_tools.get_component_data(reader, name),
            "get_component_interactions": lambda: component_tools.get_component_interactions(reader, name),
            "get_component_children":    lambda: component_tools.get_component_children(reader, name),
            "list_components":           lambda: component_tools.list_components(reader, args.get("comp_type"), args.get("limit")),
            "get_component_spec":        lambda: component_tools.get_component_spec(reader, name),
            "get_component_full":        lambda: component_tools.get_component_full(reader, name),
            "get_build_diff":            lambda: build_tools.get_build_diff(reader),
            "validate_component_implementation": lambda: validation_tool.validate_component_implementation(
                reader, name, args.get("source", ""),
            ),
        }

        fn = dispatch_map.get(tool_name)
        if not fn:
            available = ", ".join(dispatch_map.keys())
            return f"Unknown tool: {tool_name}. Available: {available}"

        return fn()

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
