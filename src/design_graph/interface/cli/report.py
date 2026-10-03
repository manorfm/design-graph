"""
Prototype report building and Markdown rendering for 'design-graph report'.

Responsibilities:
  - TokenTableRow, ComponentSummary, ScreenReport, PrototypeReport: typed domain objects
  - ReportConfig: controls which sections appear in the rendered report
  - build_prototype_report(): assembles a PrototypeReport from any GraphReader-like object
  - render_markdown_report(): serialises a PrototypeReport to a Markdown string

The reader is accepted as a duck-typed object so this module carries zero
graph-layer imports at module level (G9 guardrail).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ── Domain objects ────────────────────────────────────────────────────────────

@dataclass
class TokenTableRow:
    """A single row in the design-token table of a prototype report."""
    category: str
    label:    str
    value:    str
    usage:    int


@dataclass
class ComponentSummary:
    """Presence summary of one component within a screen section."""
    name:         str
    comp_type:    str
    occurrence:   int
    section_name: str = ""


@dataclass
class ScreenReport:
    """Report data for a single screen extracted from the prototype."""
    name:                str
    component_count:     int
    sections_count:      int
    section_names:       list[str]            = field(default_factory=list)
    component_summaries: list[ComponentSummary] = field(default_factory=list)


@dataclass
class PrototypeReport:
    """Complete report produced from a design-graph database."""
    prototype_name: str
    generated_at:   str               # ISO-8601 UTC
    node_counts:    dict[str, int]
    token_rows:     list[TokenTableRow]
    screen_reports: list[ScreenReport]


@dataclass
class ReportConfig:
    """Controls what is included when building and rendering a prototype report."""
    prototype_name:            str
    include_tokens:            bool = True
    include_jsx:               bool = False
    max_components_per_screen: int  = 20


# ── Report builder ────────────────────────────────────────────────────────────

def build_prototype_report(reader: Any, config: ReportConfig) -> PrototypeReport:
    """
    Build a PrototypeReport by querying reader for screens, tokens, and counts.
    Never raises — silently skips any reader call that fails.
    """
    generated_at   = datetime.now(timezone.utc).isoformat()
    node_counts    = _safe_count_nodes(reader)
    token_rows     = _collect_token_rows(reader) if config.include_tokens else []
    screen_reports = _collect_screen_reports(reader, config)

    return PrototypeReport(
        prototype_name=config.prototype_name,
        generated_at=generated_at,
        node_counts=node_counts,
        token_rows=token_rows,
        screen_reports=screen_reports,
    )


def _safe_count_nodes(reader: Any) -> dict[str, int]:
    try:
        return reader.count_nodes()
    except Exception as exc:
        logger.warning("report: count_nodes failed: %s", exc)
        return {}


def _collect_token_rows(reader: Any) -> list[TokenTableRow]:
    """Fetch tokens and sort by category (asc) then usage (desc)."""
    try:
        raw = reader.get_tokens()
    except Exception as exc:
        logger.warning("report: get_tokens failed: %s", exc)
        return []

    rows = [
        TokenTableRow(
            category=t.get("t.category", ""),
            label=t.get("t.label", ""),
            value=t.get("t.value", ""),
            usage=t.get("t.usage", 0),
        )
        for t in raw
    ]
    return sorted(rows, key=lambda r: (r.category, -r.usage))


def _collect_screen_reports(reader: Any, config: ReportConfig) -> list[ScreenReport]:
    """Build a ScreenReport for each screen returned by list_screens."""
    try:
        screens = reader.list_screens()
    except Exception as exc:
        logger.warning("report: list_screens failed: %s", exc)
        return []

    reports: list[ScreenReport] = []
    for s in screens:
        name   = s.get("name", "")
        detail = _safe_get_screen(reader, name)

        section_names = [
            sec["sec.name"]
            for sec in detail.get("sections", [])
            if sec.get("sec.name")
        ]
        component_summaries = [
            ComponentSummary(
                name=c.get("c.name", ""),
                comp_type=c.get("c.comp_type", ""),
                occurrence=1,
            )
            for c in detail.get("components", [])[: config.max_components_per_screen]
        ]
        reports.append(ScreenReport(
            name=name,
            component_count=s.get("component_count", 0),
            sections_count=s.get("sections_count", 0),
            section_names=section_names,
            component_summaries=component_summaries,
        ))
    return reports


def _safe_get_screen(reader: Any, name: str) -> dict:
    try:
        return reader.get_screen(name) or {}
    except Exception as exc:
        logger.warning("report: get_screen(%s) failed: %s", name, exc)
        return {}


# ── Markdown renderer ─────────────────────────────────────────────────────────

def render_markdown_report(report: PrototypeReport) -> str:
    """
    Render a PrototypeReport as a Markdown string.
    Uses only stdlib — no templating dependency.
    """
    lines: list[str] = []

    lines.append(f"# Prototype Report: {report.prototype_name}")
    lines.append("")
    lines.append(f"Generated: {report.generated_at}")
    lines.append("")

    lines += _render_overview(report.node_counts)

    if report.token_rows:
        lines += _render_token_table(report.token_rows)

    lines += _render_screens(report.screen_reports)

    return "\n".join(lines)


def _render_overview(node_counts: dict[str, int]) -> list[str]:
    lines = ["## Overview", ""]
    if node_counts:
        lines += ["| Category | Count |", "|---|---|"]
        for key in ("screens", "components", "sections", "tokens",
                    "texts", "styles", "interactions"):
            if key in node_counts:
                lines.append(f"| {key.capitalize()} | {node_counts[key]} |")
    lines.append("")
    return lines


def _render_token_table(token_rows: list[TokenTableRow]) -> list[str]:
    lines = ["## Design Tokens", "", "| Category | Label | Value | Usage |", "|---|---|---|---|"]
    for t in token_rows:
        lines.append(f"| {t.category} | {t.label} | `{t.value}` | {t.usage} |")
    lines.append("")
    return lines


def _render_screens(screen_reports: list[ScreenReport]) -> list[str]:
    lines = ["## Screens", ""]
    for sr in screen_reports:
        lines.append(f"### {sr.name}")
        lines.append("")
        lines.append(f"- Components: {sr.component_count}")
        lines.append(f"- Sections:   {sr.sections_count}")
        if sr.section_names:
            lines.append(f"- Section names: {', '.join(sr.section_names)}")
        if sr.component_summaries:
            lines += ["", "| Component | Type |", "|---|---|"]
            for c in sr.component_summaries:
                lines.append(f"| {c.name} | {c.comp_type} |")
        lines.append("")
    return lines
