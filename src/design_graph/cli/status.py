"""
Graph status collection and rendering for 'design-graph status'.

Responsibilities:
  - GraphStatusReport: typed snapshot of graph health metrics
  - collect_graph_status(): read state file + open reader + get counts
  - render_status_report(): format the report for terminal output

No direct imports from graph/ at module level (G9 guardrail).
The GraphReader is opened locally inside collect_graph_status.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_BYTES_PER_KB = 1024
_BYTES_PER_MB = 1024 * 1024


# ── Domain object ─────────────────────────────────────────────────────────────

@dataclass
class GraphStatusReport:
    """
    Immutable snapshot of a design-graph database's health.

    is_stale is True when the HTML hash in the state file differs from
    current_html_hash (the HTML file on disk has changed since last build),
    or when no previous build exists.
    """

    db_path:           Path
    db_size_bytes:     int
    last_build:        str           # ISO-8601 UTC string, empty = never built
    html_hash:         str           # hash from last build state
    current_html_hash: str           # hash of HTML file right now (may differ)
    kuzu_version:      str
    node_counts:       dict[str, int] = field(default_factory=dict)

    @property
    def is_stale(self) -> bool:
        """True when the HTML has changed since last build or was never built."""
        if not self.last_build or not self.html_hash:
            return True
        return self.html_hash != self.current_html_hash


# ── Status collection ─────────────────────────────────────────────────────────

def collect_graph_status(
    db_path: Path,
    state_path: Path,
    html_path: Optional[Path] = None,
) -> GraphStatusReport:
    """
    Build a GraphStatusReport by reading:
    - Build state from state_path (last build time, previous html_hash)
    - Node counts from db_path via GraphReader
    - Current html_hash from html_path (if provided and exists)
    - Kuzu version from the installed package

    Never raises — returns a minimal report on any error.
    """
    import hashlib

    import kuzu

    from design_graph.pipeline.state import load_build_state

    kuzu_version = getattr(kuzu, "__version__", "unknown")
    state        = load_build_state(state_path)
    db_size      = _db_size_bytes(db_path)
    node_counts: dict[str, int] = {}

    if db_path.exists():
        node_counts = _read_node_counts(db_path)

    current_hash = ""
    if html_path and html_path.exists():
        try:
            current_hash = hashlib.md5(html_path.read_bytes()).hexdigest()
        except Exception as exc:
            logger.warning("status: could not hash %s: %s", html_path, exc)

    logger.debug(
        "status: db=%s size=%d last_build=%r stale=%s",
        db_path.name, db_size, state.last_build,
        state.html_hash != current_hash if current_hash else "unknown",
    )

    return GraphStatusReport(
        db_path=db_path,
        db_size_bytes=db_size,
        last_build=state.last_build,
        html_hash=state.html_hash,
        current_html_hash=current_hash,
        kuzu_version=kuzu_version,
        node_counts=node_counts,
    )


# ── Status rendering ──────────────────────────────────────────────────────────

def render_status_report(report: GraphStatusReport) -> str:
    """
    Format a GraphStatusReport as a human-readable terminal string.
    Uses ASCII box drawing — no external dependencies, no colour codes.
    """
    w = 58
    lines: list[str] = [f"\n{'─' * w}", "  design-graph status", f"{'─' * w}"]

    # DB info
    lines.append(f"  Graph DB  : {report.db_path}")
    lines.append(f"  DB size   : {_fmt_bytes(report.db_size_bytes)}")

    if not report.last_build:
        lines.append("  Last build: never built  ← run design-graph <proto.html>")
        lines.append(f"{'─' * w}")
        return "\n".join(lines)

    # Build info
    lines.append(f"  Last build: {report.last_build}")

    stale_marker = "  [STALE — HTML changed, run design-graph --force to rebuild]"
    if report.is_stale and report.current_html_hash:
        lines.append(stale_marker)
    elif not report.current_html_hash:
        lines.append(f"  File hash : {report.html_hash}")
    else:
        lines.append(f"  File hash : {report.html_hash[:8]} (unchanged)")

    lines.append("")

    # Node counts
    nc = report.node_counts
    if nc:
        lines.append(f"  Screens:      {nc.get('screens', 0):>4}    Sections:   {nc.get('sections', 0):>4}")
        lines.append(f"  Components:   {nc.get('components', 0):>4}    Tokens:     {nc.get('tokens', 0):>4}")
        lines.append(f"  UITexts:      {nc.get('texts', 0):>4}    Styles:     {nc.get('styles', 0):>4}")
        lines.append(f"  Interactions: {nc.get('interactions', 0):>4}    CONTAINS:   {nc.get('contains', 0):>4}")
    else:
        lines.append("  No graph data found — run design-graph <proto.html> first")

    lines.append("")
    lines.append(f"  Kuzu version: {report.kuzu_version}")
    lines.append(f"{'─' * w}")
    return "\n".join(lines)


# ── Private helpers ───────────────────────────────────────────────────────────

def _db_size_bytes(db_path: Path) -> int:
    """Return total size of the database file or directory in bytes."""
    if not db_path.exists():
        return 0
    if db_path.is_file():
        return db_path.stat().st_size
    # Kuzu creates a directory for larger databases
    return sum(f.stat().st_size for f in db_path.rglob("*") if f.is_file())


def _fmt_bytes(n: int) -> str:
    if n >= _BYTES_PER_MB:
        return f"{n / _BYTES_PER_MB:.1f} MB"
    if n >= _BYTES_PER_KB:
        return f"{n / _BYTES_PER_KB:.1f} KB"
    return f"{n} B"


def _read_node_counts(db_path: Path) -> dict[str, int]:
    """Open db_path read-only and return node/rel counts via STATS_QUERIES."""
    try:
        import kuzu
        from design_graph.graph.reader import GraphReader
        from design_graph.graph.schema import initialize_schema

        db   = kuzu.Database(str(db_path), read_only=True)
        conn = kuzu.Connection(db)
        return GraphReader(conn).count_nodes()
    except Exception as exc:
        logger.warning("status: could not read node counts from %s: %s", db_path, exc)
        return {}
