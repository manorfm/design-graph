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
    ████░░░░░░░░░░░░░░░░  19%  12/64  SectionCard   ← per-item bar (rewritten in place on TTY,
                                                      cut to the terminal width so it never wraps)
    ████████████████████ 100%  64/64  RestaurantsPage
    0.9s                              ← timing on its own line
  ✓ Done in 1.8s

Parsing count reported at phase_completed (known only after extraction):
  → Parsing boundaries and tokens (47 items)  0.8s
"""

from __future__ import annotations

import logging
import shutil
import sys
import time
from typing import IO, Callable, Protocol


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
    - Phases with items: header line, then per-item updates rewritten in
      place on a TTY, then elapsed timing on its own line.
    - Parsing count: appended inline at phase_completed when total > 0.

    At most one line is open at a time — a phase's name waiting for its
    timing, or the current item. Anything else written to the stream — a
    log record through log_handler(), the items of a phase whose count
    comes at its end — first gives that line an end, and a phase whose name
    was interrupted states it again with its timing.
    """

    _ARROW = "→"
    _CHECK = "✓"
    _SKIP  = "○"
    # Back to the line start and erase it whole, so a shorter item never shows the end of a longer one.
    _REWRITE_LINE = "\r\x1b[2K"

    def __init__(self, output: IO[str] | None = None, width: Callable[[], int] | None = None) -> None:
        """width: the terminal's columns, read on every item so a resized window is followed."""
        self._out: IO[str] = output if output is not None else sys.stderr
        self._width = width or (lambda: shutil.get_terminal_size().columns)
        self._phase_has_items = False  # the phase announced its items (phase_started total > 0)
        self._open_line: str | None = None  # "phase" | "item": what the cursor's line holds, unfinished

    def log_handler(self) -> logging.Handler:
        """A handler writing log records to this stream without breaking the line progress is on."""
        return _LineAwareHandler(self)

    def phase_started(self, name: str, *, total: int) -> None:
        self._end_open_line()
        self._phase_has_items = total > 0
        line = f"  {self._ARROW} {name}" + (f" ({total} items)" if total > 0 else "")
        if self._phase_has_items:
            print(line, file=self._out)
        else:
            self._write(line, opens="phase")

    def phase_completed(
        self,
        name: str,
        *,
        elapsed_seconds: float,
        total: int = 0,
    ) -> None:
        timing = f"  {elapsed_seconds:.1f}s"
        count = f" ({total} items)" if total > 0 else ""
        if self._open_line == "phase":
            print(f"{count}{timing}", file=self._out)
        else:
            self._end_open_line(keep_item=True)
            if self._phase_has_items:
                print(timing, file=self._out)
            else:
                print(f"  {self._ARROW} {name}{count}{timing}", file=self._out)
        self._open_line = None
        self._phase_has_items = False

    def item_written(self, item_name: str, *, index: int, total: int) -> None:
        """
        Show per-item write progress.

        On a TTY: rewrites the current line in place.
        On non-TTY (CI, piped): skips individual item lines to keep logs clean.
        """
        self._write_inline_progress(item_name, index, total)

    def component_extracted(self, name: str, *, index: int, total: int) -> None:
        """
        Show per-component extraction progress.

        Mirrors item_written behaviour: rewritten on TTY, suppressed on non-TTY.
        """
        self._write_inline_progress(name, index, total)

    def build_skipped(self, reason: str) -> None:
        self._end_open_line()
        print(f"  {self._SKIP} Skipped — {reason}", file=self._out)

    def build_completed(self, *, total_seconds: float) -> None:
        self._end_open_line()
        print(f"  {self._CHECK} Done in {total_seconds:.1f}s", file=self._out)

    def _write_inline_progress(self, label: str, index: int, total: int) -> None:
        if not self._is_tty():
            return
        if self._open_line == "phase":
            self._end_open_line()  # items go below the phase's name, never over it
        # One column short of the width: a line that fills it wraps on some terminals, and \r then
        # returns only to the wrapped part, leaving the rest of the line behind.
        width = self._width()
        line = f"    {_bar(index, total, width)}  {index}/{total}  {label}"[:max(width - 1, 1)]
        self._write(f"{self._REWRITE_LINE}{line}", opens="item")

    def _end_open_line(self, *, keep_item: bool = False) -> None:
        """
        Give the open line an end: a phase's name is closed; an item is
        erased — the next one draws it again — unless it is the last word
        of its phase and kept.
        """
        if self._open_line == "item" and not keep_item:
            self._out.write(self._REWRITE_LINE)
        elif self._open_line is not None:
            self._out.write("\n")
        self._open_line = None
        self._out.flush()

    def _write(self, text: str, *, opens: str) -> None:
        self._out.write(text)
        self._out.flush()
        self._open_line = opens

    def _is_tty(self) -> bool:
        try:
            return self._out.isatty()
        except (AttributeError, ValueError):  # no isatty, or a closed stream
            return False


_BAR_DONE, _BAR_LEFT = "█", "░"
_BAR_CELLS = (10, 20)  # fewest and most cells: a quarter of the terminal's width between the two


def _bar(index: int, total: int, width: int) -> str:
    """`█████░░░░░  50%` — how far the phase went, the bar sized to the terminal."""
    done = min(max(index / total, 0.0), 1.0) if total > 0 else 0.0
    cells = min(max(width // 4, _BAR_CELLS[0]), _BAR_CELLS[1])
    filled = round(done * cells)
    return f"{_BAR_DONE * filled}{_BAR_LEFT * (cells - filled)} {round(done * 100):>3}%"


class _LineAwareHandler(logging.StreamHandler):
    """Writes each record on a line of its own, after the reporter has ended the line progress left open."""

    def __init__(self, reporter: TerminalBuildReporter) -> None:
        super().__init__(reporter._out)
        self._reporter = reporter

    def emit(self, record: logging.LogRecord) -> None:
        self._reporter._end_open_line()
        super().emit(record)


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
