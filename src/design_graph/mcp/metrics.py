"""
Append-only JSONL log of this MCP server's own tool calls, plus a pure
read/filter/aggregate API. No rendering here — mcp/tools.py renders,
mirroring the existing mcp/search.py (logic) / mcp/tools.py (rendering)
split already established in this codebase.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from design_graph.paths import data_dir

logger = logging.getLogger(__name__)

# Same Portuguese vocabulary already used consistently across ~13 "not
# found"/"ambiguous" call sites in mcp/tools.py.
_NOT_FOUND_MARKER  = "não encontrado"
_AMBIGUOUS_MARKER  = "é ambíguo"
_NO_RESULTS_MARKER = "Nenhum resultado"

_RELATIVE_RE = re.compile(r"^(\d+)([hdm])$")
_UNIT_TO_TIMEDELTA_KWARG = {"h": "hours", "d": "days", "m": "minutes"}


def metrics_path() -> Path:
    """~/.local/share/design-graph/metrics.jsonl — the call-log file."""
    return data_dir() / "metrics.jsonl"


def classify_outcome(text: str, is_error: bool) -> str:
    """
    Approximate a tool call's outcome from its rendered Markdown text and
    error flag, reusing the Portuguese phrases already used consistently
    across existing "not found"/"ambiguous" call sites in mcp/tools.py
    rather than threading a new structured return type through every tool
    method. A v1 heuristic, not a contract: a future tool that rephrases
    its message would silently fall through to "ok" here.
    """
    if is_error:
        return "error"
    if _NOT_FOUND_MARKER in text:
        return "not_found"
    if _AMBIGUOUS_MARKER in text:
        return "ambiguous"
    if _NO_RESULTS_MARKER in text:
        return "no_results"
    return "ok"


@dataclass(frozen=True)
class CallRecord:
    timestamp: str          # UTC ISO-8601, milliseconds precision
    tool: str
    prototype: str | None
    outcome: str            # "ok" | "not_found" | "ambiguous" | "no_results" | "error"
    duration_ms: float
    response_chars: int
    arguments: dict

    @classmethod
    def capture(
        cls, *, tool: str, prototype: str | None, outcome: str,
        duration_ms: float, response_chars: int, arguments: dict,
    ) -> CallRecord:
        return cls(
            timestamp=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            tool=tool,
            prototype=prototype,
            outcome=outcome,
            duration_ms=duration_ms,
            response_chars=response_chars,
            arguments=arguments,
        )


def record_call(record: CallRecord, path: Path | None = None) -> None:
    """
    Append one JSON line for `record`.

    One write() call for the whole line: under POSIX O_APPEND, a write
    smaller than PIPE_BUF is atomic against interleaving from other
    processes — relevant because one MCP server process runs per client
    connection, and more than one can be appending concurrently. No
    locking needed as long as this stays a single write() per line.
    """
    target = path or metrics_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(asdict(record), ensure_ascii=False) + "\n"
    with target.open("a", encoding="utf-8") as f:
        f.write(line)


def read_records(path: Path | None = None) -> list[CallRecord]:
    """
    Read every well-formed line. A torn trailing line (e.g. a crash
    mid-write) is skipped without losing prior valid ones.
    """
    target = path or metrics_path()
    if not target.exists():
        return []
    records: list[CallRecord] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(CallRecord(**json.loads(line)))
        except Exception:
            logger.warning("metrics: skipped malformed line in %s", target)
            continue
    return records


def _parse_time_bound(value: str) -> datetime:
    """
    Parse `value` as either a relative shorthand ("24h", "7d", "30m",
    measured back from now in UTC) or a literal ISO-8601 timestamp.
    """
    match = _RELATIVE_RE.match(value.strip())
    if match:
        amount, unit = match.groups()
        delta = timedelta(**{_UNIT_TO_TIMEDELTA_KWARG[unit]: int(amount)})
        return datetime.now(timezone.utc) - delta
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _record_timestamp(record: CallRecord) -> datetime:
    return datetime.fromisoformat(record.timestamp.replace("Z", "+00:00"))


def query_calls(
    *,
    prototype: str | None = None,
    tool: str | None = None,
    outcome: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int | None = None,
    path: Path | None = None,
) -> list[CallRecord]:
    """Filter records, newest first, optionally capped by `limit`."""
    records = read_records(path)
    if prototype:
        records = [r for r in records if r.prototype == prototype]
    if tool:
        records = [r for r in records if r.tool == tool]
    if outcome:
        records = [r for r in records if r.outcome == outcome]
    if since:
        bound = _parse_time_bound(since)
        records = [r for r in records if _record_timestamp(r) >= bound]
    if until:
        bound = _parse_time_bound(until)
        records = [r for r in records if _record_timestamp(r) <= bound]
    records = sorted(records, key=lambda r: r.timestamp, reverse=True)
    if limit is not None:
        records = records[:limit]
    return records


@dataclass(frozen=True)
class MetricsSummary:
    total: int
    by_tool: dict[str, dict[str, int]]
    by_outcome: dict[str, int]
    by_prototype: dict[str, dict[str, int]]
    not_ok_rate: float
    top_empty_queries: list[tuple[str, int]]


def _group_by_outcome(records: list[CallRecord], key) -> dict[str, dict[str, int]]:
    grouped: dict[str, dict[str, int]] = {}
    for r in records:
        bucket = grouped.setdefault(key(r), {"total": 0})
        bucket["total"] += 1
        bucket[r.outcome] = bucket.get(r.outcome, 0) + 1
    return grouped


def aggregate(records: list[CallRecord], top_n_queries: int = 10) -> MetricsSummary:
    """
    Summarize `records`, always over the full set passed in — a caller
    that also wants a capped raw list applies `limit` separately via
    query_calls(); aggregating over an arbitrarily truncated sample would
    misrepresent trends.
    """
    total = len(records)
    by_tool = _group_by_outcome(records, lambda r: r.tool)
    by_prototype = _group_by_outcome(records, lambda r: r.prototype or "(nenhum)")

    by_outcome: dict[str, int] = {}
    for r in records:
        by_outcome[r.outcome] = by_outcome.get(r.outcome, 0) + 1
    not_ok = sum(count for outcome, count in by_outcome.items() if outcome != "ok")
    not_ok_rate = (not_ok / total) if total else 0.0

    empty_queries: Counter[str] = Counter()
    for r in records:
        if r.tool == "search" and r.outcome != "ok":
            query = r.arguments.get("query")
            if query:
                empty_queries[query] += 1

    return MetricsSummary(
        total=total,
        by_tool=by_tool,
        by_outcome=by_outcome,
        by_prototype=by_prototype,
        not_ok_rate=not_ok_rate,
        top_empty_queries=empty_queries.most_common(top_n_queries),
    )
