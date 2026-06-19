"""Application boundary for graph discovery, selection, and user preferences."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from design_graph.core.graph_catalog import (
    GraphCatalog,
    GraphDocumentName,
    GraphSelection,
    SelectedGraph,
)
from design_graph.paths import config_dir, load_user_config, resolve_graph_dir


@dataclass(frozen=True)
class GraphWorkspace:
    """Aggregate that applies one selection policy to every application surface."""

    catalog: GraphCatalog
    configuration: dict

    @classmethod
    def open(cls) -> "GraphWorkspace":
        return cls(
            catalog=GraphCatalog.discover(resolve_graph_dir()),
            configuration=load_user_config(),
        )

    def select(self, db_path: Path | None = None, document: str | None = None) -> SelectedGraph:
        return self.catalog.select(GraphSelection(
            db_path=db_path,
            document=self._name(document),
            environment_document=self._name(os.environ.get("DESIGN_GRAPH_DOC")),
            configured_document=self._name(self.configuration.get("default_doc")),
        ))

    def set_default(self, document: str) -> SelectedGraph:
        selected = self.catalog.select(GraphSelection(document=GraphDocumentName(document)))
        updated = dict(self.configuration)
        updated["default_doc"] = selected.database.name.value
        destination = config_dir() / "config.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
        temporary.replace(destination)
        return selected

    @staticmethod
    def _name(value: str | None) -> GraphDocumentName | None:
        return GraphDocumentName(value) if value and value.strip() else None

