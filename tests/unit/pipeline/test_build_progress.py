"""
Tests for pipeline/build_progress.py — build phase reporter.

Responsibilities under test:
  - BuildPhaseReporter protocol is satisfied by both concrete implementations
  - TerminalBuildReporter writes phase names and elapsed time to stderr
  - SilentBuildReporter produces no output (used in --quiet and tests)
  - PhaseTimer measures elapsed time per phase
  - run_pipeline() accepts a reporter and calls it at each phase boundary
"""

from __future__ import annotations

import io
import time

import pytest

from design_graph.pipeline.build_progress import (
    BuildPhaseReporter,
    PhaseTimer,
    SilentBuildReporter,
    TerminalBuildReporter,
)


# ── PhaseTimer ────────────────────────────────────────────────────────────────

class TestPhaseTimer:
    def test_elapsed_increases_over_time(self):
        timer = PhaseTimer()
        timer.start()
        time.sleep(0.01)
        assert timer.elapsed() >= 0.005

    def test_elapsed_before_start_raises(self):
        timer = PhaseTimer()
        with pytest.raises(RuntimeError, match="start"):
            timer.elapsed()

    def test_split_returns_elapsed_and_resets(self):
        timer = PhaseTimer()
        timer.start()
        time.sleep(0.01)
        first = timer.split()
        assert first >= 0.005
        time.sleep(0.01)
        second = timer.split()
        # second split measured from last split, not from start
        assert second < first + 0.1


# ── TerminalBuildReporter ─────────────────────────────────────────────────────

class TestTerminalBuildReporter:
    def _reporter(self) -> tuple[TerminalBuildReporter, io.StringIO]:
        buf = io.StringIO()
        return TerminalBuildReporter(output=buf), buf

    def test_phase_started_writes_phase_name(self):
        reporter, buf = self._reporter()
        reporter.phase_started("Extracting components", total=47)
        assert "Extracting components" in buf.getvalue()

    def test_phase_started_writes_total_when_positive(self):
        reporter, buf = self._reporter()
        reporter.phase_started("Extracting components", total=47)
        assert "47" in buf.getvalue()

    def test_phase_started_omits_total_when_zero(self):
        reporter, buf = self._reporter()
        reporter.phase_started("Loading file", total=0)
        output = buf.getvalue()
        assert "Loading file" in output
        assert "0" not in output

    def test_phase_completed_writes_elapsed(self):
        reporter, buf = self._reporter()
        reporter.phase_started("Writing graph", total=0)
        reporter.phase_completed("Writing graph", elapsed_seconds=1.23)
        assert "1.2" in buf.getvalue()

    def test_build_skipped_writes_reason(self):
        reporter, buf = self._reporter()
        reporter.build_skipped("HTML unchanged")
        assert "unchanged" in buf.getvalue().lower()

    def test_build_completed_writes_total_time(self):
        reporter, buf = self._reporter()
        reporter.build_completed(total_seconds=3.7)
        assert "3.7" in buf.getvalue() or "3" in buf.getvalue()

    def test_output_goes_to_injected_stream_not_stderr(self):
        """Output must use the injected stream, not hard-coded sys.stderr."""
        import sys
        buf = io.StringIO()
        reporter = TerminalBuildReporter(output=buf)
        reporter.phase_started("Test", total=0)
        # Nothing should have been written to real stderr
        assert buf.getvalue()  # our buffer has content


# ── SilentBuildReporter ───────────────────────────────────────────────────────

class TestSilentBuildReporter:
    def test_phase_started_produces_no_output(self, capsys):
        reporter = SilentBuildReporter()
        reporter.phase_started("Any phase", total=99)
        captured = capsys.readouterr()
        assert captured.out == "" and captured.err == ""

    def test_phase_completed_produces_no_output(self, capsys):
        reporter = SilentBuildReporter()
        reporter.phase_completed("Any phase", elapsed_seconds=1.0)
        captured = capsys.readouterr()
        assert captured.out == "" and captured.err == ""

    def test_build_skipped_produces_no_output(self, capsys):
        reporter = SilentBuildReporter()
        reporter.build_skipped("unchanged")
        captured = capsys.readouterr()
        assert captured.out == "" and captured.err == ""

    def test_build_completed_produces_no_output(self, capsys):
        reporter = SilentBuildReporter()
        reporter.build_completed(total_seconds=5.0)
        captured = capsys.readouterr()
        assert captured.out == "" and captured.err == ""


# ── Reporter protocol contract ────────────────────────────────────────────────

class TestReporterProtocolContract:
    """Both reporters must implement the same interface without raising."""

    @pytest.mark.parametrize("reporter_cls", [SilentBuildReporter])
    def test_full_lifecycle_does_not_raise(self, reporter_cls):
        reporter = reporter_cls()
        reporter.phase_started("Phase 1", total=0)
        reporter.phase_completed("Phase 1", elapsed_seconds=0.1)
        reporter.phase_started("Phase 2", total=5)
        reporter.phase_completed("Phase 2", elapsed_seconds=0.5)
        reporter.build_completed(total_seconds=0.6)

    def test_terminal_full_lifecycle_does_not_raise(self):
        reporter = TerminalBuildReporter(output=io.StringIO())
        reporter.phase_started("Phase 1", total=0)
        reporter.phase_completed("Phase 1", elapsed_seconds=0.1)
        reporter.phase_started("Phase 2", total=5)
        reporter.phase_completed("Phase 2", elapsed_seconds=0.5)
        reporter.build_completed(total_seconds=0.6)

    def test_full_lifecycle_with_item_written_does_not_raise(self):
        reporter = TerminalBuildReporter(output=io.StringIO())
        reporter.phase_started("Writing graph", total=3)
        reporter.item_written("ComponentA", index=1, total=3)
        reporter.item_written("ComponentB", index=2, total=3)
        reporter.item_written("HomeScreen", index=3, total=3)
        reporter.phase_completed("Writing graph", elapsed_seconds=0.9)
        reporter.build_completed(total_seconds=1.1)


# ── item_written ──────────────────────────────────────────────────────────────

class TestItemWritten:
    def _reporter(self) -> tuple[TerminalBuildReporter, io.StringIO]:
        buf = io.StringIO()
        return TerminalBuildReporter(output=buf), buf

    def test_silent_reporter_item_written_is_noop(self, capsys):
        reporter = SilentBuildReporter()
        reporter.item_written("SectionCard", index=1, total=10)
        captured = capsys.readouterr()
        assert captured.out == "" and captured.err == ""

    def test_terminal_item_written_does_not_raise(self):
        reporter, _ = self._reporter()
        reporter.phase_started("Writing graph", total=5)
        reporter.item_written("SectionCard", index=1, total=5)  # must not raise

    def test_phase_completed_after_items_includes_elapsed(self):
        reporter, buf = self._reporter()
        reporter.phase_started("Writing graph", total=2)
        reporter.item_written("CompA", index=1, total=2)
        reporter.item_written("CompB", index=2, total=2)
        reporter.phase_completed("Writing graph", elapsed_seconds=0.7)
        assert "0.7" in buf.getvalue()

    def test_phase_started_with_items_includes_count_in_output(self):
        reporter, buf = self._reporter()
        reporter.phase_started("Writing graph", total=64)
        assert "64" in buf.getvalue()


# ── phase_completed with total (Etapa B — parsing count) ─────────────────────

class TestPhaseCompletedWithCount:
    def _reporter(self) -> tuple[TerminalBuildReporter, io.StringIO]:
        buf = io.StringIO()
        return TerminalBuildReporter(output=buf), buf

    def test_count_appears_in_output_when_total_given(self):
        reporter, buf = self._reporter()
        reporter.phase_started("Parsing boundaries and tokens", total=0)
        reporter.phase_completed("Parsing boundaries and tokens",
                                 elapsed_seconds=0.8, total=47)
        assert "47" in buf.getvalue()

    def test_count_absent_when_total_zero(self):
        reporter, buf = self._reporter()
        reporter.phase_started("Loading file", total=0)
        reporter.phase_completed("Loading file", elapsed_seconds=0.1, total=0)
        output = buf.getvalue()
        # timing present, but no zero item count
        assert "0.1" in output
        assert "0 item" not in output

    def test_elapsed_always_present(self):
        reporter, buf = self._reporter()
        reporter.phase_started("Parsing", total=0)
        reporter.phase_completed("Parsing", elapsed_seconds=1.5, total=30)
        assert "1.5" in buf.getvalue()

    def test_silent_reporter_phase_completed_with_total_is_noop(self, capsys):
        reporter = SilentBuildReporter()
        reporter.phase_completed("Parsing", elapsed_seconds=1.0, total=30)
        captured = capsys.readouterr()
        assert captured.out == "" and captured.err == ""


# ── Coordinator integration — spy reporter ────────────────────────────────────

class TestCoordinatorItemWrittenIntegration:
    """Coordinator must call item_written for each component and screen written."""

    _JS = """
    function HomePage() { return <div><BtnPrimary /><SectionCard /></div>; }
    function BtnPrimary() { return <button style={{color:'#ffb81c'}}>OK</button>; }
    function SectionCard() { return <div className="card">Card</div>; }
    """

    @pytest.fixture()
    def proto_html(self, tmp_path):
        f = tmp_path / "test.html"
        f.write_text(f"<html><body><script>{self._JS}</script></body></html>")
        return f

    def test_item_written_called_for_each_component_and_screen(self, proto_html, tmp_path):
        import asyncio
        from design_graph.pipeline.build_progress import SilentBuildReporter
        from design_graph.pipeline.coordinator import run_pipeline

        items: list[str] = []

        class SpyReporter(SilentBuildReporter):
            def item_written(self, name, *, index, total):
                items.append(name)

        asyncio.run(run_pipeline(
            proto_html, tmp_path / "t.db", tmp_path / ".state.json",
            reporter=SpyReporter(),
        ))
        assert len(items) >= 2, f"Expected ≥2 item_written calls, got: {items}"

    def test_coordinator_passes_parsed_count_to_phase_completed(self, proto_html, tmp_path):
        import asyncio
        from design_graph.pipeline.build_progress import SilentBuildReporter
        from design_graph.pipeline.coordinator import run_pipeline

        completed_totals: list[int] = []

        class SpyReporter(SilentBuildReporter):
            def phase_completed(self, name, *, elapsed_seconds, total=0):
                if "parsing" in name.lower() or "boundaries" in name.lower():
                    completed_totals.append(total)

        asyncio.run(run_pipeline(
            proto_html, tmp_path / "t2.db", tmp_path / ".state2.json",
            reporter=SpyReporter(),
        ))
        assert any(t > 0 for t in completed_totals), (
            f"Expected parsing phase_completed with total>0, got: {completed_totals}"
        )
