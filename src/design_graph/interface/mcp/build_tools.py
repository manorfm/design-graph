"""Build tools: what changed in the last build and how the tools have been used."""

from __future__ import annotations

from design_graph.model.graph.reader import GraphReader
from design_graph.interface.mcp.notices import truncation_notice


DEFAULT_METRICS_LIMIT = 500


_METRICS_OUTCOMES = ("ok", "not_found", "ambiguous", "no_results", "error")


def get_metrics(
    doc: str | None = None,
    tool: str | None = None,
    outcome: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int | None = None,
    raw: bool = False,
) -> str:
    from design_graph.interface.mcp.metrics import aggregate, query_calls

    # No `limit` passed here on purpose: the aggregate must summarize
    # the full filtered set, never an arbitrarily truncated sample —
    # `limit` only caps how many rows raw=true renders, applied below.
    records = query_calls(prototype=doc, tool=tool, outcome=outcome, since=since, until=until)
    if not records:
        return "Nenhuma chamada registrada para os filtros informados."
    if raw:
        return _render_metrics_raw(records, limit)
    return _render_metrics_summary(aggregate(records))


def _render_metrics_raw(records: list, limit: int | None) -> str:
    effective_limit = limit if limit and limit > 0 else DEFAULT_METRICS_LIMIT
    shown = records[:effective_limit]
    lines = [
        "## Chamadas registradas", f"({len(records)} encontradas)\n",
        "| Timestamp | Ferramenta | Prototype | Outcome | Duração (ms) |",
        "|---|---|---|---|---|",
    ]
    for r in shown:
        lines.append(f"| {r.timestamp} | {r.tool} | {r.prototype or '-'} | {r.outcome} | {r.duration_ms:.1f} |")
    notice = truncation_notice(len(records), len(shown))
    if notice:
        lines.append(notice + " (passe limit= para ver mais)")
    return "\n".join(lines)


def _render_metrics_summary(summary) -> str:
    lines = ["## Métricas de uso", f"({summary.total} chamadas)\n"]
    lines.append("| Ferramenta | Total | " + " | ".join(_METRICS_OUTCOMES) + " |")
    lines.append("|---|---|" + "---|" * len(_METRICS_OUTCOMES))
    for tool_name, counts in sorted(summary.by_tool.items(), key=lambda kv: -kv[1]["total"]):
        row = [tool_name, str(counts["total"])] + [str(counts.get(o, 0)) for o in _METRICS_OUTCOMES]
        lines.append("| " + " | ".join(row) + " |")

    lines.append(f"\n**Taxa não-ok:** {summary.not_ok_rate:.1%}")

    if summary.by_prototype:
        lines.append("\n### Por prototype")
        lines.append("| Prototype | Total | Taxa não-ok |")
        lines.append("|---|---|---|")
        for proto, counts in sorted(summary.by_prototype.items(), key=lambda kv: -kv[1]["total"]):
            total = counts["total"]
            not_ok = total - counts.get("ok", 0)
            rate = (not_ok / total) if total else 0.0
            lines.append(f"| {proto} | {total} | {rate:.1%} |")

    if summary.top_empty_queries:
        lines.append("\n### Buscas sem resultado (top)")
        lines.append("| Query | Ocorrências |")
        lines.append("|---|---|")
        for query, count in summary.top_empty_queries:
            lines.append(f"| {query} | {count} |")

    return "\n".join(lines)


def get_build_diff(reader: GraphReader) -> str:
    diff = reader.get_build_diff()
    if diff is None:
        return (
            "Nenhum diff de build disponível para este documento "
            "(protótipo carregado sem state.json associado, ou nunca reconstruído)."
        )

    # Surfaced regardless of which message below fires — a build can
    # skip bundle entries on its very first run, or on a run with no
    # screen/component changes, and this was previously visible only in
    # a stderr log line during `design-graph <file>` (source_loader.py),
    # never through any MCP tool (docs/changes/C39).
    skipped = diff.get("skipped_entries", 0)
    skipped_notice = (
        f"⚠ {skipped} entrada(s) do bundle do protótipo falharam ao decodificar nesta "
        "build e foram descartadas — a extração está incompleta para o(s) arquivo(s)-fonte "
        "afetado(s). Rode `design-graph --verbose <proto.html>` para ver quais.\n\n"
        if skipped else ""
    )

    if diff.get("is_first_build"):
        return skipped_notice + "Primeira build deste protótipo — não há build anterior para comparar."

    screens_added   = diff.get("screens_added", [])
    screens_removed = diff.get("screens_removed", [])
    comps_added     = diff.get("comps_added", [])
    comps_removed   = diff.get("comps_removed", [])
    if not any((screens_added, screens_removed, comps_added, comps_removed)):
        return skipped_notice + "Nenhuma mudança de telas ou componentes desde a build anterior."

    lines = [skipped_notice + "# Diff da última build\n"]
    if screens_added:
        lines.append(f"**Telas adicionadas**: {', '.join(screens_added)}")
    if screens_removed:
        lines.append(f"**Telas removidas**: {', '.join(screens_removed)}")
    if comps_added:
        lines.append(f"**Componentes adicionados**: {', '.join(comps_added)}")
    if comps_removed:
        lines.append(f"**Componentes removidos**: {', '.join(comps_removed)}")
    return "\n".join(lines)
