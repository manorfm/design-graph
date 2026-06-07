"""
Build phase progress reporting.

Defines the BuildPhaseReporter protocol and two concrete implementations:
  - TerminalBuildReporter: writes human-readable phase progress to a stream
  - SilentBuildReporter: no-op, used in --quiet mode, JSON output, and tests

Separates pipeline timing concerns from terminal output so that coordinator.py
stays testable without capturing I/O.

Terminal output model
─────────────────────
Phases WITHOUT item progress (total=0 in phase_started):
  → Loading myapp.html  0.1s          ← name + timing on one line

Phases WITH item progress (total>0 in phase_started):
  → Writing graph (64 items)          ← header line (with newline)
    [12/64] SectionCard               ← per-item update (overwritten via \\r on TTY)
    [64/64] RestaurantsPage
    0.9s                              ← timing on its own line
  ✓ Done in 1.8s

Parsing count reported at phase_completed (known only after extraction):
  → Parsing boundaries and tokens (47 items)  0.8s
"""

from __future__ import annotations

import sys
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
        """Called when a phase begins. total > 0 signals a phase with trackable items."""
        ...

    def phase_completed(self, name: str, *, elapsed_seconds: float, total: int = 0) -> None:
        """
        Called when a phase finishes.

        total > 0 appends an item count to the phase line — used by the parsing
        phase where the count is known only after extraction completes.
        """
        ...

    def item_written(self, item_name: str, *, index: int, total: int) -> None:
        """Called after each item is written during the write phase."""
        ...

    def component_extracted(self, name: str, *, index: int, total: int) -> None:
        """Called after each component is extracted during the parse phase."""
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

    - Phases without items: single inline line (name + timing).
    - Phases with items: header line, then per-item updates (\\r on TTY),
      then elapsed timing on its own line.
    - Parsing count: appended inline at phase_completed when total > 0.
    """

    _ARROW = "→"
    _CHECK = "✓"
    _SKIP  = "○"
    _ITEM_WIDTH = 40  # characters reserved for item name column (padding for \\r overwrite)

    def __init__(self, output: IO[str] | None = None) -> None:
        self._out: IO[str] = output if output is not None else sys.stderr
        self._phase_has_items: bool = False  # True when phase_started(total>0)
        self._item_line_active: bool = False  # True after first item_written in a phase

    def phase_started(self, name: str, *, total: int) -> None:
        suffix = f" ({total} items)" if total > 0 else ""
        line   = f"  {self._ARROW} {name}{suffix}"
        if total > 0:
            # Write header on its own line; items will appear below
            print(line, file=self._out)
            self._phase_has_items = True
        else:
            # Inline mode: timing appended by phase_completed
            print(line, end="", flush=True, file=self._out)
            self._phase_has_items = False
        self._item_line_active = False

    def phase_completed(
        self,
        name: str,
        *,
        elapsed_seconds: float,
        total: int = 0,
    ) -> None:
        timing = f"  {elapsed_seconds:.1f}s"

        if self._phase_has_items:
            # End any active item line, then print timing alone
            if self._item_line_active:
                print(file=self._out)  # newline after last \r item
            print(timing, file=self._out)
        else:
            # Inline mode: append count (if known at completion) + timing
            count_suffix = f" ({total} items)" if total > 0 else ""
            print(f"{count_suffix}{timing}", file=self._out)

        self._phase_has_items = False
        self._item_line_active = False

    def item_written(self, item_name: str, *, index: int, total: int) -> None:
        """
        Show per-item write progress.

        On a TTY: overwrites the current line in-place via \\r.
        On non-TTY (CI, piped): skips individual item lines to keep logs clean.
        """
        self._write_inline_progress(item_name, index, total)

    def component_extracted(self, name: str, *, index: int, total: int) -> None:
        """
        Show per-component extraction progress.

        Mirrors item_written behaviour: overwrites on TTY, suppressed on non-TTY.
        """
        self._write_inline_progress(name, index, total)

    def _write_inline_progress(self, label: str, index: int, total: int) -> None:
        try:
            is_tty = self._out.isatty()
        except AttributeError:
            is_tty = False

        if is_tty:
            line = f"    [{index}/{total}] {label}"
            padded = line.ljust(self._ITEM_WIDTH)
            self._out.write(f"\r{padded}")
            self._out.flush()
            self._item_line_active = True

    def build_skipped(self, reason: str) -> None:
        print(f"  {self._SKIP} Skipped — {reason}", file=self._out)

    def build_completed(self, *, total_seconds: float) -> None:
        print(f"  {self._CHECK} Done in {total_seconds:.1f}s", file=self._out)


class SilentBuildReporter:
    """No-op reporter. Used when --quiet is set or JSON output is requested."""

    def phase_started(self, name: str, *, total: int) -> None:
        pass

    def phase_completed(
        self,
        name: str,
        *,
        elapsed_seconds: float,
        total: int = 0,
    ) -> None:
        pass

    def item_written(self, item_name: str, *, index: int, total: int) -> None:
        pass

    def component_extracted(self, name: str, *, index: int, total: int) -> None:
        pass

    def build_skipped(self, reason: str) -> None:
        pass

    def build_completed(self, *, total_seconds: float) -> None:
        pass
