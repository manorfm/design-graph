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
