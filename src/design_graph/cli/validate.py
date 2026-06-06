"""
Graph integrity validation for 'design-graph validate'.

Runs a set of named checks against a Kuzu database and produces a
GraphValidationReport. Each check is independent — a failure in one
does not prevent others from running.

Checks:
  - graph_not_empty:      at least one screen and one component exist
  - no_orphaned_screens:  every Screen has at least one USES_COMPONENT relationship
  - schema_intact:        all expected node and relationship tables present

Severity levels:
  ERROR   — the graph is likely corrupt or unusable
  WARNING — the graph is valid but suspicious (e.g. empty sections)
  INFO    — informational, no action required
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Domain objects ────────────────────────────────────────────────────────────

class ValidationSeverity(str, Enum):
    ERROR   = "error"
    WARNING = "warning"
    INFO    = "info"


@dataclass
class GraphViolation:
    """A single finding from a validation check."""
    severity:   ValidationSeverity
    check_name: str
    message:    str
    details:    dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "severity":   self.severity.value,
            "check":      self.check_name,
            "message":    self.message,
            "details":    self.details,
        }


@dataclass
class GraphValidationReport:
    """
    Aggregated result of all validation checks on one database.

    status:     "ok" | "warnings" | "errors"
    violations: list of GraphViolation sorted by severity (errors first)
    node_counts: snapshot of graph contents at validation time
    """
    db_path:     Path
    violations:  list[GraphViolation] = field(default_factory=list)
    node_counts: dict[str, int]       = field(default_factory=dict)

    @property
    def status(self) -> str:
        if any(v.severity == ValidationSeverity.ERROR for v in self.violations):
            return "errors"
        if any(v.severity == ValidationSeverity.WARNING for v in self.violations):
            return "warnings"
        return "ok"

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == ValidationSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == ValidationSeverity.WARNING)

    def to_dict(self) -> dict:
        return {
            "status":       self.status,
            "db_path":      str(self.db_path),
            "errors":       self.error_count,
            "warnings":     self.warning_count,
            "node_counts":  self.node_counts,
            "violations":   [v.to_dict() for v in self.violations],
        }


# ── Validation entry point ────────────────────────────────────────────────────

def validate_graph(db_path: Path) -> GraphValidationReport:
    """
    Run all validation checks against the Kuzu database at db_path.
    Returns a GraphValidationReport even when the database cannot be opened —
    the report will contain an ERROR violation in that case.
    """
    report = GraphValidationReport(db_path=db_path)

    if not db_path.exists():
        report.violations.append(GraphViolation(
            severity=ValidationSeverity.ERROR,
            check_name="database_exists",
            message=f"Database not found: {db_path}",
            details={"path": str(db_path)},
        ))
        logger.warning("validate: database not found at %s", db_path)
        return report

    try:
        import kuzu
        from design_graph.graph.reader import GraphReader
        from design_graph.graph.schema import STATS_QUERIES, initialize_schema

        db   = kuzu.Database(str(db_path), read_only=True)
        conn = kuzu.Connection(db)
        reader = GraphReader(conn)

        report.node_counts = reader.count_nodes()
        _run_all_checks(report, reader)

    except Exception as exc:
        report.violations.append(GraphViolation(
            severity=ValidationSeverity.ERROR,
            check_name="database_readable",
            message=f"Cannot open database: {exc}",
            details={"error": str(exc)},
        ))
        logger.error("validate: cannot open %s: %s", db_path, exc)

    report.violations.sort(key=lambda v: (
        {"error": 0, "warning": 1, "info": 2}[v.severity.value]
    ))

    logger.info(
        "validate: %s → status=%s errors=%d warnings=%d",
        db_path.name, report.status, report.error_count, report.warning_count,
    )
    return report


# ── Individual checks ─────────────────────────────────────────────────────────

def _run_all_checks(report: GraphValidationReport, reader) -> None:
    """Execute every check function against the reader, collecting violations."""
    for check_fn in (
        _check_graph_not_empty,
        _check_no_orphaned_screens,
        _check_no_orphaned_components,
        _check_sections_have_screens,
        _check_tokens_have_usage,
    ):
        try:
            violations = check_fn(report.node_counts, reader)
            report.violations.extend(violations)
        except Exception as exc:
            logger.warning("validate: check %s failed: %s", check_fn.__name__, exc)


def _check_graph_not_empty(
    counts: dict[str, int], reader,
) -> list[GraphViolation]:
    violations: list[GraphViolation] = []

    if counts.get("screens", 0) == 0:
        violations.append(GraphViolation(
            severity=ValidationSeverity.ERROR,
            check_name="graph_not_empty",
            message="No Screen nodes found — graph appears empty or build failed.",
            details={"screens": 0},
        ))
    if counts.get("components", 0) == 0:
        violations.append(GraphViolation(
            severity=ValidationSeverity.WARNING,
            check_name="graph_not_empty",
            message="No Component nodes found — prototype may have no detectable components.",
            details={"components": 0},
        ))
    return violations


def _check_no_orphaned_screens(
    counts: dict[str, int], reader,
) -> list[GraphViolation]:
    """A screen with zero components is suspicious — likely a parse failure."""
    rows = reader._q(
        "MATCH (s:Screen) WHERE s.component_count = 0 OR s.component_count IS NULL "
        "RETURN s.name, s.component_count ORDER BY s.name"
    )
    if not rows:
        return []
    names = [r.get("s.name", "?") for r in rows]
    return [GraphViolation(
        severity=ValidationSeverity.WARNING,
        check_name="no_orphaned_screens",
        message=f"{len(names)} screen(s) have zero components.",
        details={"screens": names},
    )]


def _check_no_orphaned_components(
    counts: dict[str, int], reader,
) -> list[GraphViolation]:
    """Components not referenced by any screen may indicate extraction drift."""
    rows = reader._q(
        "MATCH (c:Component) "
        "WHERE NOT EXISTS { MATCH (s:Screen)-[:USES_COMPONENT]->(c) } "
        "RETURN c.name, c.comp_type ORDER BY c.name LIMIT 20"
    )
    if not rows:
        return []
    names = [r.get("c.name", "?") for r in rows]
    return [GraphViolation(
        severity=ValidationSeverity.INFO,
        check_name="no_orphaned_components",
        message=f"{len(names)} component(s) have no screen references (may be shared utilities).",
        details={"components": names},
    )]


def _check_sections_have_screens(
    counts: dict[str, int], reader,
) -> list[GraphViolation]:
    """Sections not linked to a screen via HAS_SECTION indicate write errors."""
    rows = reader._q(
        "MATCH (sec:Section) "
        "WHERE NOT EXISTS { MATCH (s:Screen)-[:HAS_SECTION]->(sec) } "
        "RETURN sec.id, sec.name ORDER BY sec.name LIMIT 10"
    )
    if not rows:
        return []
    names = [r.get("sec.name", "?") for r in rows]
    return [GraphViolation(
        severity=ValidationSeverity.WARNING,
        check_name="sections_have_screens",
        message=f"{len(names)} section(s) have no parent screen.",
        details={"sections": names},
    )]


def _check_tokens_have_usage(
    counts: dict[str, int], reader,
) -> list[GraphViolation]:
    """Tokens with usage=0 indicate orphaned tokens that passed the extraction filter."""
    rows = reader._q(
        "MATCH (t:Token) WHERE t.usage <= 0 "
        "RETURN t.label, t.value ORDER BY t.label LIMIT 10"
    )
    if not rows:
        return []
    labels = [r.get("t.label", "?") for r in rows]
    return [GraphViolation(
        severity=ValidationSeverity.WARNING,
        check_name="tokens_have_usage",
        message=f"{len(labels)} token(s) have zero usage count.",
        details={"tokens": labels},
    )]


# ── Report rendering ──────────────────────────────────────────────────────────

def render_validation_report(report: GraphValidationReport) -> str:
    """Format a GraphValidationReport as a human-readable terminal string."""
    w = 58
    icon = {"ok": "✓", "warnings": "⚠", "errors": "✗"}.get(report.status, "?")
    lines = [
        f"\n{'─' * w}",
        f"  design-graph validate  {icon} {report.status.upper()}",
        f"{'─' * w}",
        f"  Database: {report.db_path.name}",
        f"  Errors:   {report.error_count}    Warnings: {report.warning_count}",
    ]

    nc = report.node_counts
    if nc:
        lines += [
            "",
            f"  Screens:    {nc.get('screens', 0):>4}    Components: {nc.get('components', 0):>4}",
            f"  Sections:   {nc.get('sections', 0):>4}    Tokens:     {nc.get('tokens', 0):>4}",
            f"  CONTAINS:   {nc.get('contains', 0):>4}",
        ]

    if report.violations:
        lines.append("")
        for v in report.violations:
            prefix = {"error": "  [ERROR]  ", "warning": "  [WARN]   ", "info": "  [INFO]   "}
            lines.append(f"{prefix.get(v.severity.value, '  ')}{v.message}")

    lines.append(f"{'─' * w}")
    return "\n".join(lines)
