"""Tests for mcp/metrics.py — call-log writer, reader, filter and aggregate."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from design_graph.mcp.metrics import (
    CallRecord,
    _parse_time_bound,
    aggregate,
    classify_outcome,
    metrics_path,
    query_calls,
    read_records,
    record_call,
)


class TestClassifyOutcome:
    def test_error_flag_wins_even_with_ok_looking_text(self):
        assert classify_outcome("tudo certo", is_error=True) == "error"

    def test_not_found_phrase(self):
        assert classify_outcome("Componente 'X' não encontrado. Use search('X').", False) == "not_found"

    def test_ambiguous_phrase(self):
        assert classify_outcome("Nome 'X' é ambíguo: component='A', screen='B'.", False) == "ambiguous"

    def test_no_results_phrase(self):
        assert classify_outcome("Nenhum resultado para 'xyz'.", False) == "no_results"

    def test_defaults_to_ok(self):
        assert classify_outcome("# Spec: BtnPrimary\n...", False) == "ok"

    def test_error_takes_precedence_over_not_found_text(self):
        assert classify_outcome("Componente 'X' não encontrado.", is_error=True) == "error"


class TestParseTimeBound:
    def test_iso_with_z_suffix(self):
        parsed = _parse_time_bound("2026-01-01T00:00:00Z")
        assert parsed == datetime(2026, 1, 1, tzinfo=timezone.utc)

    def test_iso_with_explicit_offset(self):
        parsed = _parse_time_bound("2026-01-01T00:00:00+00:00")
        assert parsed == datetime(2026, 1, 1, tzinfo=timezone.utc)

    def test_relative_hours(self):
        before = datetime.now(timezone.utc) - timedelta(hours=24)
        parsed = _parse_time_bound("24h")
        assert abs((parsed - before).total_seconds()) < 5

    def test_relative_days(self):
        before = datetime.now(timezone.utc) - timedelta(days=7)
        parsed = _parse_time_bound("7d")
        assert abs((parsed - before).total_seconds()) < 5

    def test_relative_minutes(self):
        before = datetime.now(timezone.utc) - timedelta(minutes=30)
        parsed = _parse_time_bound("30m")
        assert abs((parsed - before).total_seconds()) < 5


class TestMetricsPath:
    def test_ends_with_metrics_jsonl(self):
        assert metrics_path().name == "metrics.jsonl"


def _record(**overrides) -> CallRecord:
    defaults = dict(
        timestamp="2026-01-01T00:00:00.000+00:00",
        tool="search",
        prototype="toToggle",
        outcome="ok",
        duration_ms=1.5,
        response_chars=100,
        arguments={"query": "MemberRow"},
    )
    defaults.update(overrides)
    return CallRecord(**defaults)


class TestRecordAndReadRoundTrip:
    def test_single_record_round_trips(self, tmp_path):
        path = tmp_path / "metrics.jsonl"
        record_call(_record(), path=path)
        got = read_records(path)
        assert len(got) == 1
        assert got[0] == _record()

    def test_multiple_calls_append_multiple_lines(self, tmp_path):
        path = tmp_path / "metrics.jsonl"
        record_call(_record(tool="search"), path=path)
        record_call(_record(tool="get_component_spec"), path=path)
        got = read_records(path)
        assert [r.tool for r in got] == ["search", "get_component_spec"]

    def test_missing_file_returns_empty_list(self, tmp_path):
        assert read_records(tmp_path / "nope.jsonl") == []

    def test_parent_directory_created_on_write(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "metrics.jsonl"
        record_call(_record(), path=path)
        assert path.exists()

    def test_corrupted_trailing_line_is_skipped_without_losing_prior_lines(self, tmp_path):
        path = tmp_path / "metrics.jsonl"
        record_call(_record(tool="search"), path=path)
        with path.open("a", encoding="utf-8") as f:
            f.write("{not valid json\n")
        got = read_records(path)
        assert len(got) == 1
        assert got[0].tool == "search"


class TestQueryCallsFiltering:
    def _seed(self, tmp_path):
        path = tmp_path / "metrics.jsonl"
        record_call(_record(tool="search", prototype="toToggle", outcome="ok",
                             timestamp="2026-01-01T00:00:00.000+00:00"), path=path)
        record_call(_record(tool="get_component_spec", prototype="ipede-v7", outcome="not_found",
                             timestamp="2026-01-02T00:00:00.000+00:00"), path=path)
        record_call(_record(tool="search", prototype="toToggle", outcome="no_results",
                             timestamp="2026-01-03T00:00:00.000+00:00"), path=path)
        return path

    def test_filter_by_prototype(self, tmp_path):
        path = self._seed(tmp_path)
        got = query_calls(prototype="ipede-v7", path=path)
        assert len(got) == 1
        assert got[0].tool == "get_component_spec"

    def test_filter_by_tool(self, tmp_path):
        path = self._seed(tmp_path)
        got = query_calls(tool="search", path=path)
        assert len(got) == 2

    def test_filter_by_outcome(self, tmp_path):
        path = self._seed(tmp_path)
        got = query_calls(outcome="not_found", path=path)
        assert len(got) == 1

    def test_filter_by_since(self, tmp_path):
        path = self._seed(tmp_path)
        got = query_calls(since="2026-01-02T00:00:00Z", path=path)
        assert len(got) == 2

    def test_filter_by_until(self, tmp_path):
        path = self._seed(tmp_path)
        got = query_calls(until="2026-01-01T12:00:00Z", path=path)
        assert len(got) == 1

    def test_combined_filters(self, tmp_path):
        path = self._seed(tmp_path)
        got = query_calls(tool="search", outcome="no_results", path=path)
        assert len(got) == 1
        assert got[0].timestamp == "2026-01-03T00:00:00.000+00:00"

    def test_results_are_newest_first(self, tmp_path):
        path = self._seed(tmp_path)
        got = query_calls(path=path)
        timestamps = [r.timestamp for r in got]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_limit_caps_result_count(self, tmp_path):
        path = self._seed(tmp_path)
        got = query_calls(limit=1, path=path)
        assert len(got) == 1

    def test_no_filters_returns_everything(self, tmp_path):
        path = self._seed(tmp_path)
        assert len(query_calls(path=path)) == 3


class TestAggregate:
    def test_empty_input_has_zero_total_and_no_crash(self):
        summary = aggregate([])
        assert summary.total == 0
        assert summary.not_ok_rate == 0.0
        assert summary.by_tool == {}
        assert summary.top_empty_queries == []

    def test_total_counts_all_records(self):
        records = [_record(), _record(), _record()]
        assert aggregate(records).total == 3

    def test_by_tool_breaks_down_per_tool_and_outcome(self):
        records = [
            _record(tool="search", outcome="ok"),
            _record(tool="search", outcome="no_results"),
            _record(tool="get_component_spec", outcome="ok"),
        ]
        summary = aggregate(records)
        assert summary.by_tool["search"]["total"] == 2
        assert summary.by_tool["search"]["ok"] == 1
        assert summary.by_tool["search"]["no_results"] == 1
        assert summary.by_tool["get_component_spec"]["total"] == 1

    def test_by_prototype_breaks_down_per_prototype(self):
        records = [
            _record(prototype="toToggle", outcome="ok"),
            _record(prototype="toToggle", outcome="error"),
            _record(prototype="ipede-v7", outcome="ok"),
        ]
        summary = aggregate(records)
        assert summary.by_prototype["toToggle"]["total"] == 2
        assert summary.by_prototype["ipede-v7"]["total"] == 1

    def test_not_ok_rate_excludes_ok_outcomes(self):
        records = [_record(outcome="ok"), _record(outcome="ok"),
                   _record(outcome="not_found"), _record(outcome="error")]
        summary = aggregate(records)
        assert summary.not_ok_rate == pytest.approx(0.5)

    def test_top_empty_queries_only_from_search_with_non_ok_outcome(self):
        records = [
            _record(tool="search", outcome="no_results", arguments={"query": "botao cinza"}),
            _record(tool="search", outcome="no_results", arguments={"query": "botao cinza"}),
            _record(tool="search", outcome="ok", arguments={"query": "MemberRow"}),
            _record(tool="get_component_spec", outcome="not_found", arguments={"name": "Ghost"}),
        ]
        summary = aggregate(records)
        assert summary.top_empty_queries == [("botao cinza", 2)]

    def test_top_empty_queries_respects_top_n(self):
        records = [
            _record(tool="search", outcome="no_results", arguments={"query": f"q{i}"})
            for i in range(15)
        ]
        summary = aggregate(records, top_n_queries=5)
        assert len(summary.top_empty_queries) == 5
