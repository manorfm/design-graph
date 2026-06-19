"""Domain model for graph database discovery and deterministic selection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


@dataclass(frozen=True)
class GraphDocumentName:
    """Validated prototype identifier, independent from its filesystem suffix."""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip()
        if normalized.lower().endswith(".db"):
            normalized = normalized[:-3]
        if not normalized:
            raise ValueError("graph document name cannot be empty")
        object.__setattr__(self, "value", normalized)

    def matches(self, candidate: "GraphDocumentName") -> bool:
        return self.value.casefold() == candidate.value.casefold()


@dataclass(frozen=True)
class GraphDatabase:
    """A discovered graph database with behavior derived from its path."""

    path: Path

    @property
    def name(self) -> GraphDocumentName:
        return GraphDocumentName(self.path.name)

    @property
    def state_path(self) -> Path:
        return self.path.with_name(f"{self.path.name}.state.json")

    @property
    def size_bytes(self) -> int:
        if not self.path.exists():
            return 0
        if self.path.is_file():
            return self.path.stat().st_size
        return sum(item.stat().st_size for item in self.path.rglob("*") if item.is_file())

    @property
    def modified_at(self) -> float:
        return self.path.stat().st_mtime if self.path.exists() else 0.0


class GraphSelectionSource(str, Enum):
    EXPLICIT_PATH = "--db"
    EXPLICIT_DOCUMENT = "--doc"
    ENVIRONMENT = "DESIGN_GRAPH_DOC"
    USER_CONFIG = "config default_doc"
    ONLY_DATABASE = "only database"


@dataclass(frozen=True)
class GraphSelection:
    """Selection intent ordered from strongest to weakest source."""

    db_path: Path | None = None
    document: GraphDocumentName | None = None
    environment_document: GraphDocumentName | None = None
    configured_document: GraphDocumentName | None = None


@dataclass(frozen=True)
class SelectedGraph:
    database: GraphDatabase
    source: GraphSelectionSource


class GraphCatalogError(RuntimeError):
    pass


class NoGraphDatabases(GraphCatalogError):
    pass


class AmbiguousGraphSelection(GraphCatalogError):
    def __init__(self, names: tuple[GraphDocumentName, ...]) -> None:
        available = ", ".join(repr(name.value) for name in names)
        super().__init__(
            f"Multiple graph databases found: {available}. "
            "Select one with --doc NAME or 'design-graph db use NAME'."
        )


class UnknownGraphDocument(GraphCatalogError):
    def __init__(self, requested: GraphDocumentName, names: tuple[GraphDocumentName, ...]) -> None:
        available = ", ".join(repr(name.value) for name in names) or "(none)"
        super().__init__(f"Graph document {requested.value!r} not found. Available: {available}")


@dataclass(frozen=True)
class GraphCatalog:
    """Collection root that owns discovery and all graph-selection rules."""

    directory: Path
    databases: tuple[GraphDatabase, ...]

    @classmethod
    def discover(cls, directory: Path) -> "GraphCatalog":
        paths = directory.glob("*.db") if directory.exists() else ()
        databases = tuple(
            GraphDatabase(path)
            for path in sorted(paths, key=lambda item: item.stem.casefold())
        )
        return cls(directory=directory, databases=databases)

    @property
    def names(self) -> tuple[GraphDocumentName, ...]:
        return tuple(database.name for database in self.databases)

    def select(self, intent: GraphSelection) -> SelectedGraph:
        if intent.db_path is not None:
            return SelectedGraph(GraphDatabase(intent.db_path.expanduser().resolve()), GraphSelectionSource.EXPLICIT_PATH)

        candidates = (
            (intent.document, GraphSelectionSource.EXPLICIT_DOCUMENT),
            (intent.environment_document, GraphSelectionSource.ENVIRONMENT),
            (intent.configured_document, GraphSelectionSource.USER_CONFIG),
        )
        for requested, source in candidates:
            if requested is not None:
                return SelectedGraph(self._find(requested), source)

        if not self.databases:
            raise NoGraphDatabases(
                f"No graphs found in {self.directory}. Run: design-graph <prototype.html>"
            )
        if len(self.databases) > 1:
            raise AmbiguousGraphSelection(self.names)
        return SelectedGraph(self.databases[0], GraphSelectionSource.ONLY_DATABASE)

    def _find(self, requested: GraphDocumentName) -> GraphDatabase:
        for database in self.databases:
            if requested.matches(database.name):
                return database
        raise UnknownGraphDocument(requested, self.names)
