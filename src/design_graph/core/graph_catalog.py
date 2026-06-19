"""Domain model for graph database discovery and deterministic selection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
import shutil


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
        if normalized in {".", ".."}:
            raise ValueError("graph document name cannot be a path segment")
        if Path(normalized).name != normalized or "/" in normalized or "\\" in normalized:
            raise ValueError("graph document name must be a single filename stem")
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
        return GraphArtifact(self.path, GraphArtifactKind.DATABASE).size_bytes

    @property
    def modified_at(self) -> float:
        return self.path.stat().st_mtime if self.path.exists() else 0.0

    @property
    def build_temp_path(self) -> Path:
        return self.path.parent / f".{self.path.name}.building"


class GraphArtifactKind(str, Enum):
    DATABASE = "database"
    STATE = "state"
    BUILD_TEMP = "build-temp"


@dataclass(frozen=True)
class BuildArtifactRetention:
    """Safety policy preventing prune from deleting an active build."""

    minimum_age: timedelta = timedelta(hours=1)

    def considers_stale(self, artifact: "GraphArtifact", now: datetime | None = None) -> bool:
        if not artifact.exists:
            return False
        reference = now or datetime.now(timezone.utc)
        modified = datetime.fromtimestamp(artifact.path.stat().st_mtime, timezone.utc)
        return reference - modified >= self.minimum_age


@dataclass(frozen=True)
class GraphArtifact:
    """One filesystem artifact owned by graph maintenance."""

    path: Path
    kind: GraphArtifactKind

    @property
    def exists(self) -> bool:
        return self.path.exists() or self.path.is_symlink()

    @property
    def size_bytes(self) -> int:
        if not self.exists:
            return 0
        if self.path.is_symlink() or self.path.is_file():
            return self.path.lstat().st_size
        return sum(item.stat().st_size for item in self.path.rglob("*") if item.is_file())

    def remove(self) -> bool:
        if not self.exists:
            return False
        if self.path.is_symlink() or self.path.is_file():
            self.path.unlink()
        else:
            shutil.rmtree(self.path)
        return True


@dataclass(frozen=True)
class MaintenanceResult:
    """Immutable outcome distinguishing planned from deleted artifacts."""

    planned: tuple[GraphArtifact, ...]
    removed: tuple[GraphArtifact, ...] = ()
    planned_bytes: int = 0
    reclaimed_bytes: int = 0

    @property
    def removed_count(self) -> int:
        return len(self.removed)

@dataclass(frozen=True)
class GraphMaintenancePlan:
    """Executable, inspectable plan for one destructive maintenance operation."""

    operation: str
    artifacts: tuple[GraphArtifact, ...]
    document: GraphDocumentName | None = None

    @property
    def is_empty(self) -> bool:
        return not self.artifacts

    def preview(self) -> MaintenanceResult:
        return MaintenanceResult(
            planned=self.artifacts,
            planned_bytes=sum(artifact.size_bytes for artifact in self.artifacts),
        )

    def execute(self) -> MaintenanceResult:
        measured = tuple((artifact, artifact.size_bytes) for artifact in self.artifacts)
        removed_with_sizes = tuple(
            (artifact, size) for artifact, size in measured if artifact.remove()
        )
        removed = tuple(artifact for artifact, _ in removed_with_sizes)
        return MaintenanceResult(
            planned=self.artifacts,
            removed=removed,
            planned_bytes=sum(size for _, size in measured),
            reclaimed_bytes=sum(size for _, size in removed_with_sizes),
        )


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

    def plan_removal(self, document: GraphDocumentName) -> GraphMaintenancePlan:
        database = self._find(document)
        candidates = (
            GraphArtifact(database.state_path, GraphArtifactKind.STATE),
            GraphArtifact(database.build_temp_path, GraphArtifactKind.BUILD_TEMP),
            GraphArtifact(database.path, GraphArtifactKind.DATABASE),
        )
        return GraphMaintenancePlan(
            operation="remove",
            document=database.name,
            artifacts=tuple(artifact for artifact in candidates if artifact.exists),
        )

    def plan_prune(
        self,
        retention: BuildArtifactRetention | None = None,
        now: datetime | None = None,
    ) -> GraphMaintenancePlan:
        if not self.directory.exists():
            return GraphMaintenancePlan(operation="prune", artifacts=())
        artifacts: list[GraphArtifact] = []
        for state_path in sorted(self.directory.glob("*.db.state.json")):
            database_path = Path(str(state_path)[:-len(".state.json")])
            if not database_path.exists():
                artifacts.append(GraphArtifact(state_path, GraphArtifactKind.STATE))
        policy = retention or BuildArtifactRetention()
        for temp_path in sorted(self.directory.glob(".*.db.building")):
            artifact = GraphArtifact(temp_path, GraphArtifactKind.BUILD_TEMP)
            if policy.considers_stale(artifact, now):
                artifacts.append(artifact)
        return GraphMaintenancePlan(operation="prune", artifacts=tuple(artifacts))
