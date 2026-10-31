"""
MCP tool dispatch.

Each tool lives in a module grouped by what it is about (screens, components,
full sources, discovery, builds, validation) and returns Markdown. This
module only decides which prototype a call is about and routes it.

ToolDispatcher.pick_reader() resolves which prototype to use:
  Priority: explicit doc= argument → session active_doc → auto-select → error
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from design_graph.model.graph.catalog import GraphDocumentName

if TYPE_CHECKING:
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
        if tool_name == "get_binding_context":
            from design_graph.interface.mcp.binding_context_tool import (
                get_binding_context,
            )

            return get_binding_context(args)

        if tool_name in {"get_full", "assemble_page"}:
            from design_graph.interface.mcp.qualified_source_tool import (
                QUALIFIED_KEYS,
                qualified_source,
            )

            if QUALIFIED_KEYS.intersection(args):
                return qualified_source(tool_name, args)

        # Legacy consumers are deliberately not dependencies of qualified retrieval.
        from design_graph.interface.mcp import (
            assemble_tool,
            asset_tool,
            build_tools,
            component_tools,
            discovery_tools,
            full_tools,
            screen_tools,
            validation_tool,
        )

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
            "assemble_page":             lambda: assemble_tool.assemble_page(
                reader, name, args.get("known"), args.get("part", 1),
            ),
            "get_screen":                lambda: screen_tools.get_screen(
                reader, name or screen, section, args.get("detail", "outline"), str(args.get("compare") or ""),
            ),
            "get_component":             lambda: component_tools.get_component(reader, name, args.get("depth", 0)),
            "get_tokens":                lambda: discovery_tools.get_tokens(
                reader, args.get("category"), args.get("screen"), args.get("mode"),
            ),
            "get_resources":             lambda: discovery_tools.get_resources(reader, args.get("kind"), args.get("screen")),
            "get_asset":                 lambda: asset_tool.get_asset(reader, name, Path.cwd()),
            "get_full":                  lambda: full_tools.get_full(
                reader, name, args.get("aspect", ""), screen, section, args.get("part", 1),
            ),
            "impact":                    lambda: discovery_tools.impact(reader, name),
            "list_components":           lambda: component_tools.list_components(reader, args.get("comp_type"), args.get("limit")),
            "get_build_diff":            lambda: build_tools.get_build_diff(reader),
            "validate_component_implementation": lambda: validation_tool.validate_component_implementation(
                reader, name, args.get("source", ""),
            ),
        }

        fn = dispatch_map.get(tool_name)
        if not fn:
            available = ", ".join(dispatch_map.keys())
            return f"Unknown tool: {tool_name}. Available: {available}"

        if tool_name == "get_full" and args.get("aspect") == "source":
            from types import SimpleNamespace

            from design_graph.interface.mcp.automatic_source_tool import (
                automatic_source,
            )

            assert reader is not None
            source = reader.get_full_source(name)
            if not source:
                return automatic_source(reader, name, args.get("part", 1))
            # The legacy formatter receives the already resolved record. Status never
            # depends on rendered text, and the reader is queried exactly once.
            return full_tools.get_full_source(
                cast("GraphReader", SimpleNamespace(get_full_source=lambda _: source)), name, args.get("part", 1),
            )

        if tool_name == "assemble_page":
            from design_graph.interface.mcp.qualified_source_tool import (
                assemble_with_coverage,
            )

            return assemble_with_coverage(reader, name, args.get("known"), args.get("part", 1))
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
