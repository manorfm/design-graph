"""
TDD — Etapa 3: Per-component extraction progress reporting.

Tests for:
- BuildPhaseReporter.component_extracted protocol method
- TerminalBuildReporter.component_extracted output behaviour
- extract_all_components on_component_extracted callback
- Coordinator integration: reporter receives component_extracted calls
"""

from __future__ import annotations

import asyncio
import io
from collections import Counter
from unittest.mock import MagicMock

import pytest

from design_graph.core.models import FunctionBoundary
from design_graph.pipeline.build_progress import (
    BuildPhaseReporter,
    SilentBuildReporter,
    TerminalBuildReporter,
)


# ── Protocol ──────────────────────────────────────────────────────────────────

class TestComponentExtractedProtocol:
    def test_silent_reporter_has_component_extracted_method(self):
        reporter = SilentBuildReporter()
        assert hasattr(reporter, "component_extracted")

    def test_terminal_reporter_has_component_extracted_method(self):
        reporter = TerminalBuildReporter(output=io.StringIO())
        assert hasattr(reporter, "component_extracted")

    def test_silent_reporter_component_extracted_is_noop(self, capsys):
        reporter = SilentBuildReporter()
        reporter.component_extracted("NavBar", index=1, total=10)
        captured = capsys.readouterr()
        assert captured.out == "" and captured.err == ""

    def test_terminal_reporter_component_extracted_does_not_raise(self):
        buf = io.StringIO()
        reporter = TerminalBuildReporter(output=buf)
        reporter.phase_started("Extracting components", total=5)
        reporter.component_extracted("NavBar", index=1, total=5)


# ── TerminalBuildReporter output ──────────────────────────────────────────────

class TestTerminalComponentExtractedOutput:
    def _reporter(self):
        buf = io.StringIO()
        return TerminalBuildReporter(output=buf), buf

    def test_component_extracted_writes_count_and_name_on_tty(self, monkeypatch):
        """On a TTY stream, component_extracted overwrites the line with progress."""
        buf = io.StringIO()
        monkeypatch.setattr(buf, "isatty", lambda: True)
        reporter = TerminalBuildReporter(output=buf)
        reporter.phase_started("Extracting components", total=5)
        reporter.component_extracted("NavBar", index=2, total=5)
        out = buf.getvalue()
        assert "2" in out
        assert "5" in out
        assert "NavBar" in out

    def test_component_extracted_skips_output_on_non_tty(self, monkeypatch):
        """On non-TTY (CI/pipe), per-item extraction lines are suppressed."""
        buf = io.StringIO()
        monkeypatch.setattr(buf, "isatty", lambda: False)
        reporter = TerminalBuildReporter(output=buf)
        reporter.phase_started("Extracting components", total=5)
        reporter.component_extracted("NavBar", index=2, total=5)
        # Only the phase_started header should be in output; no item lines
        assert "NavBar" not in buf.getvalue()

    def test_full_extraction_phase_lifecycle_does_not_raise(self):
        reporter, buf = self._reporter()
        reporter.phase_started("Extracting components", total=3)
        reporter.component_extracted("CompA", index=1, total=3)
        reporter.component_extracted("CompB", index=2, total=3)
        reporter.component_extracted("CompC", index=3, total=3)
        reporter.phase_completed("Extracting components", elapsed_seconds=0.4)


# ── extract_all_components callback ──────────────────────────────────────────

class TestExtractAllComponentsCallback:
    _JS = (
        "function NavBar() { return <nav className='nav'/>; }"
        "function SectionCard() { return <div className='card'><p>Hello</p></div>; }"
    )

    def _make_boundaries(self) -> list[FunctionBoundary]:
        from design_graph.parsing.js_parser import find_all_boundaries
        from design_graph.core.models import RawSources
        return find_all_boundaries(self._JS)

    def test_callback_called_once_per_extracted_component(self):
        from design_graph.extraction.component_extractor import extract_all_components
        boundaries = self._make_boundaries()
        calls: list[tuple[str, int, int]] = []

        def on_extracted(name: str, index: int, total: int) -> None:
            calls.append((name, index, total))

        asyncio.run(extract_all_components(
            self._JS, boundaries, Counter(b.name for b in boundaries), {},
            on_component_extracted=on_extracted,
        ))
        assert len(calls) == len(boundaries)

    def test_callback_receives_correct_total(self):
        from design_graph.extraction.component_extractor import extract_all_components
        boundaries = self._make_boundaries()
        totals: list[int] = []

        asyncio.run(extract_all_components(
            self._JS, boundaries, Counter(b.name for b in boundaries), {},
            on_component_extracted=lambda name, idx, total: totals.append(total),
        ))
        assert all(t == len(boundaries) for t in totals)

    def test_callback_index_covers_one_to_n(self):
        from design_graph.extraction.component_extractor import extract_all_components
        boundaries = self._make_boundaries()
        indices: list[int] = []

        asyncio.run(extract_all_components(
            self._JS, boundaries, Counter(b.name for b in boundaries), {},
            on_component_extracted=lambda name, idx, total: indices.append(idx),
        ))
        assert sorted(indices) == list(range(1, len(boundaries) + 1))

    def test_no_callback_works_without_error(self):
        from design_graph.extraction.component_extractor import extract_all_components
        boundaries = self._make_boundaries()
        result = asyncio.run(extract_all_components(
            self._JS, boundaries, Counter(b.name for b in boundaries), {},
        ))
        assert len(result) > 0

    def test_empty_boundaries_with_callback_never_calls_callback(self):
        from design_graph.extraction.component_extractor import extract_all_components
        calls = []
        asyncio.run(extract_all_components(
            self._JS, [], Counter(), {},
            on_component_extracted=lambda n, i, t: calls.append(n),
        ))
        assert calls == []


# ── Coordinator integration ───────────────────────────────────────────────────

class TestCoordinatorExtractionProgressIntegration:
    _JS = """
    function HomePage() { return <div><NavBar /><ContentGrid /></div>; }
    function NavBar() { return <nav className='nav'/>; }
    function ContentGrid() { return <section className='grid'/>; }
    """

    @pytest.fixture()
    def proto_html(self, tmp_path):
        f = tmp_path / "proto.html"
        f.write_text(f"<html><body><script>{self._JS}</script></body></html>")
        return f

    def test_coordinator_calls_component_extracted_for_each_component(
        self, proto_html, tmp_path
    ):
        from design_graph.pipeline.coordinator import run_pipeline

        extracted_names: list[str] = []

        class SpyReporter(SilentBuildReporter):
            def component_extracted(self, name, *, index, total):
                extracted_names.append(name)

        asyncio.run(run_pipeline(
            proto_html,
            tmp_path / "t.db",
            tmp_path / ".state.json",
            reporter=SpyReporter(),
        ))
        assert len(extracted_names) >= 2, (
            f"Expected ≥2 component_extracted calls, got: {extracted_names}"
        )

    def test_coordinator_component_extracted_index_is_sequential(
        self, proto_html, tmp_path
    ):
        from design_graph.pipeline.coordinator import run_pipeline

        indices: list[int] = []

        class SpyReporter(SilentBuildReporter):
            def component_extracted(self, name, *, index, total):
                indices.append(index)

        asyncio.run(run_pipeline(
            proto_html,
            tmp_path / "t2.db",
            tmp_path / ".state2.json",
            reporter=SpyReporter(),
        ))
        if indices:
            assert sorted(indices) == list(range(1, max(indices) + 1))
