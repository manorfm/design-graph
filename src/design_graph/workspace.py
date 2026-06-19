"""Application boundary for graph discovery, selection, maintenance, and preferences."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from design_graph.core.graph_catalog import (
    GraphArtifactKind,
    GraphCatalog,
    GraphDocumentName,
    GraphSelection,
    GraphMaintenancePlan,
    MaintenanceResult,
    SelectedGraph,
)
from design_graph.paths import config_dir, load_user_config, resolve_graph_dir


@dataclass(frozen=True)
class UserConfiguration:
    """User preferences with behavior for prototype selection."""

    values: dict

    @property
    def default_document(self) -> GraphDocumentName | None:
        value = str(self.values.get("default_doc", "")).strip()
        return GraphDocumentName(value) if value else None

    def selects(self, document: GraphDocumentName) -> bool:
        return bool(self.default_document and self.default_document.matches(document))

    def with_default(self, document: GraphDocumentName) -> "UserConfiguration":
        updated = dict(self.values)
        updated["default_doc"] = document.value
        return UserConfiguration(updated)

    def without_default(self) -> "UserConfiguration":
        updated = dict(self.values)
        updated.pop("default_doc", None)
        return UserConfiguration(updated)


@dataclass(frozen=True)
class UserConfigurationRepository:
    """Atomic persistence boundary for user preferences."""

    path: Path

    @classmethod
    def standard(cls) -> "UserConfigurationRepository":
        return cls(config_dir() / "config.json")

    def load(self) -> UserConfiguration:
        return UserConfiguration(load_user_config())

    def save(self, configuration: UserConfiguration) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(configuration.values, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)


@dataclass(frozen=True)
class GraphWorkspace:
    """Aggregate applying one policy to selection and graph lifecycle operations."""

    catalog: GraphCatalog
    configuration: UserConfiguration
    configuration_repository: UserConfigurationRepository

    @classmethod
    def open(cls) -> "GraphWorkspace":
        repository = UserConfigurationRepository.standard()
        return cls(
            catalog=GraphCatalog.discover(resolve_graph_dir()),
            configuration=repository.load(),
            configuration_repository=repository,
        )

    def select(self, db_path: Path | None = None, document: str | None = None) -> SelectedGraph:
        return self.catalog.select(GraphSelection(
            db_path=db_path,
            document=self._name(document),
            environment_document=self._name(os.environ.get("DESIGN_GRAPH_DOC")),
            configured_document=self.configuration.default_document,
        ))

    def set_default(self, document: str) -> SelectedGraph:
        selected = self.catalog.select(GraphSelection(document=GraphDocumentName(document)))
        self.configuration_repository.save(self.configuration.with_default(selected.database.name))
        return selected

    def remove(self, document: str) -> MaintenanceResult:
        name = GraphDocumentName(document)
        plan = self.catalog.plan_removal(name)
        return self.execute_maintenance(plan)

    def execute_maintenance(self, plan: GraphMaintenancePlan) -> MaintenanceResult:
        result = plan.execute()
        database_was_removed = any(
            artifact.kind is GraphArtifactKind.DATABASE for artifact in result.removed
        )
        if database_was_removed and plan.document and self.configuration.selects(plan.document):
            self.configuration_repository.save(self.configuration.without_default())
        return result

    @staticmethod
    def _name(value: str | None) -> GraphDocumentName | None:
        return GraphDocumentName(value) if value and value.strip() else None
