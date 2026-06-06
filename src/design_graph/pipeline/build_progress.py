"""
Build phase progress reporting.

Defines the BuildPhaseReporter protocol and two concrete implementations:
  - TerminalBuildReporter: writes human-readable phase progress to a stream
  - SilentBuildReporter: no-op, used in --quiet mode, JSON output, and tests

Separates pipeline timing concerns from terminal output so that coordinator.py
stays testable without capturing I/O.
"""

from __future__ import annotations

import io
import time
from typing import IO, Protocol


# ── Protocol ──────────────────────────────────────────────────────────────────

class BuildPhaseReporter(Protocol):
    """
    Receives build lifecycle events from run_pipeline().

    Implementations decide how (or whether) to display them.
    All methods must be synchronous and non-blocking.
    """

    def phase_started(self, name: str, *, total: int) -> None:
        """Called when a pipeline phase begins. total > 0 means N items to process."""
        ...

    def phase_completed(self, name: str, *, elapsed_seconds: float) -> None:
        """Called when a phase finishes. elapsed_seconds is wall-clock time for that phase."""
        ...

    def build_skipped(self, reason: str) -> None:
        """Called when the build is skipped (e.g. HTML unchanged)."""
        ...

    def build_completed(self, *, total_seconds: float) -> None:
        """Called at the very end of a successful build."""
        ...


# ── PhaseTimer ────────────────────────────────────────────────────────────────

class PhaseTimer:
    """
    Lightweight monotonic timer for measuring individual build phases.

    Usage:
        timer = PhaseTimer()
        timer.start()
        elapsed = timer.split()   # seconds since start or last split
    """

    def __init__(self) -> None:
        self._mark: float | None = None

    def start(self) -> None:
        self._mark = time.monotonic()

    def elapsed(self) -> float:
        if self._mark is None:
            raise RuntimeError("PhaseTimer.elapsed() called before start()")
        return time.monotonic() - self._mark

    def split(self) -> float:
        """Return elapsed since last split (or start) and reset the mark."""
        elapsed = self.elapsed()
        self._mark = time.monotonic()
        return elapsed


# ── Concrete implementations ──────────────────────────────────────────────────

class TerminalBuildReporter:
    """
    Writes phase progress to a text stream (default: sys.stderr).

    Output is intentionally minimal — one line per event — so it does not
    interfere with JSON stdout output or log formatting.

    Example output:
        → Loading myapp.html
        → Detecting boundaries and tokens (1 item)
        → Extracting components (47 items)     1.4s
        → Writing graph nodes                  0.9s
        ✓ Done in 3.1s
    """

    _ARROW  = "→"
    _CHECK  = "✓"
    _SKIP   = "○"

    def __init__(self, output: IO[str] | None = None) -> None:
        import sys
        self._out: IO[str] = output if output is not None else sys.stderr
        self._current_phase: str = ""

    def phase_started(self, name: str, *, total: int) -> None:
        suffix = f" ({total} items)" if total > 0 else ""
        line = f"  {self._ARROW} {name}{suffix}"
        self._current_phase = line
        print(line, end="", flush=True, file=self._out)

    def phase_completed(self, name: str, *, elapsed_seconds: float) -> None:
        timing = f"  {elapsed_seconds:.1f}s"
        print(timing, file=self._out)

    def build_skipped(self, reason: str) -> None:
        print(f"  {self._SKIP} Skipped — {reason}", file=self._out)

    def build_completed(self, *, total_seconds: float) -> None:
        print(f"  {self._CHECK} Done in {total_seconds:.1f}s", file=self._out)


class SilentBuildReporter:
    """No-op reporter. Used when --quiet is set or JSON output is requested."""

    def phase_started(self, name: str, *, total: int) -> None:
        pass

    def phase_completed(self, name: str, *, elapsed_seconds: float) -> None:
        pass

    def build_skipped(self, reason: str) -> None:
        pass

    def build_completed(self, *, total_seconds: float) -> None:
        pass
