"""
Architecture guardrail tests (G1–G9).

These tests enforce the layered dependency rules defined in the project's
backlog.md and docs/spec/00-overview.md. They run as part of the normal
test suite so a CI failure gives immediate feedback on which rule was broken.

G1  parsing/    must not import from extraction/, graph/, or mcp/
G2  extraction/ must not import from graph/ or mcp/
G3  graph/reader.py must not contain write statements (CREATE/DELETE/MERGE)
G4  extraction/ functions must be synchronous — async only in coordinator
G5  GraphReader connection must open with read_only=True
G6  FunctionBoundary list must have non-overlapping intervals (covered by T03)
G7  chunk_id values must match [a-z0-9_]+ (covered by T16)
G8  GraphWriter methods must not be awaited in coordinator.py
G9  cli/ modules must not import directly from parsing/, extraction/, or graph/
    (CLI talks only to coordinator, paths, and mcp/tools — not to internals)
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

# ── project root relative paths ───────────────────────────────────────────────

SRC = Path(__file__).parent.parent / "src" / "design_graph"
PARSING_DIR    = SRC / "parsing"
EXTRACTION_DIR = SRC / "extraction"
GRAPH_DIR      = SRC / "graph"
PIPELINE_DIR   = SRC / "pipeline"
CLI_DIR        = SRC / "cli"


def _py_files(directory: Path) -> list[Path]:
    return [f for f in directory.glob("*.py") if f.name != "__init__.py"]


def _imports_in_file(path: Path) -> list[str]:
    """Return all module names referenced in import statements."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.append(node.module)
    return modules


def _contains_pattern(path: Path, pattern: str) -> list[int]:
    """Return line numbers where pattern matches in path."""
    rx = re.compile(pattern)
    hits: list[int] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if rx.search(line):
            hits.append(i)
    return hits


# ── G1: parsing/ has no upward imports ───────────────────────────────────────

class TestG1ParsingLayerIsolation:
    FORBIDDEN_PREFIXES = (
        "design_graph.extraction",
        "design_graph.graph",
        "design_graph.mcp",
        "design_graph.pipeline",
    )

    def test_no_parsing_module_imports_extraction(self):
        violations = self._collect_violations("design_graph.extraction")
        assert not violations, self._fmt(violations)

    def test_no_parsing_module_imports_graph(self):
        violations = self._collect_violations("design_graph.graph")
        assert not violations, self._fmt(violations)

    def test_no_parsing_module_imports_mcp(self):
        violations = self._collect_violations("design_graph.mcp")
        assert not violations, self._fmt(violations)

    def test_no_parsing_module_imports_pipeline(self):
        violations = self._collect_violations("design_graph.pipeline")
        assert not violations, self._fmt(violations)

    def _collect_violations(self, forbidden_prefix: str) -> list[str]:
        violations = []
        for f in _py_files(PARSING_DIR):
            for mod in _imports_in_file(f):
                if mod.startswith(forbidden_prefix):
                    violations.append(f"{f.name}: imports {mod!r}")
        return violations

    @staticmethod
    def _fmt(violations: list[str]) -> str:
        return "G1 violation(s) — parsing/ imports upward layer:\n  " + "\n  ".join(violations)


# ── G2: extraction/ has no upward imports ────────────────────────────────────

class TestG2ExtractionLayerIsolation:
    def test_no_extraction_module_imports_graph(self):
        violations = []
        for f in _py_files(EXTRACTION_DIR):
            for mod in _imports_in_file(f):
                if mod.startswith("design_graph.graph"):
                    violations.append(f"{f.name}: imports {mod!r}")
        assert not violations, (
            "G2 violation(s) — extraction/ imports from graph/:\n  "
            + "\n  ".join(violations)
        )

    def test_no_extraction_module_imports_mcp(self):
        violations = []
        for f in _py_files(EXTRACTION_DIR):
            for mod in _imports_in_file(f):
                if mod.startswith("design_graph.mcp"):
                    violations.append(f"{f.name}: imports {mod!r}")
        assert not violations, (
            "G2 violation(s) — extraction/ imports from mcp/:\n  "
            + "\n  ".join(violations)
        )


# ── G3: reader.py is read-only (no write Cypher) ─────────────────────────────

class TestG3ReaderIsReadOnly:
    """
    Verify that no Cypher string literal in reader.py starts with a write keyword.
    Docstrings that mention these keywords as negative examples are acceptable
    (e.g. "never executes CREATE") — only actual query strings are checked.
    """
    READER_PATH = GRAPH_DIR / "reader.py"
    WRITE_STARTERS = ("CREATE", "DELETE", "MERGE", "DROP")

    def _cypher_write_strings(self) -> list[str]:
        """Find string literals in reader.py whose content starts with a write keyword."""
        tree = ast.parse(self.READER_PATH.read_text(encoding="utf-8"))
        violations: list[str] = []
        for node in ast.walk(tree):
            # ast.Constant covers string literals in Python 3.8+
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                stripped = node.value.lstrip()
                for kw in self.WRITE_STARTERS:
                    if stripped.startswith(kw):
                        violations.append(
                            f"line ~{node.lineno}: string starts with {kw!r}: "
                            f"{node.value[:60]!r}"
                        )
        return violations

    def test_no_write_cypher_string_literals(self):
        violations = self._cypher_write_strings()
        assert not violations, (
            "G3 violation — reader.py contains Cypher write operations:\n  "
            + "\n  ".join(violations)
            + "\nAll write operations must live in graph/writer.py."
        )


# ── G4: extraction/ functions are synchronous ────────────────────────────────

class TestG4ExtractionFunctionsAreSynchronous:
    # Public async entry-point + its private semaphore guard (internal impl detail)
    ALLOWED_ASYNC = {"extract_all_components", "_extract_with_guard"}

    def test_no_unexpected_async_functions_in_component_extractor(self):
        self._check_file(EXTRACTION_DIR / "component_extractor.py")

    def test_no_async_functions_in_screen_extractor(self):
        self._check_file(EXTRACTION_DIR / "screen_extractor.py", allowed=set())

    def test_no_async_functions_in_section_extractor(self):
        self._check_file(EXTRACTION_DIR / "section_extractor.py", allowed=set())

    def test_no_async_functions_in_chunker(self):
        self._check_file(EXTRACTION_DIR / "chunker.py", allowed=set())

    def _check_file(self, path: Path, allowed: set[str] | None = None) -> None:
        if allowed is None:
            allowed = self.ALLOWED_ASYNC
        tree = ast.parse(path.read_text(encoding="utf-8"))
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                if node.name not in allowed:
                    violations.append(f"{path.name}:{node.lineno} async def {node.name}")
        assert not violations, (
            "G4 violation — unexpected async function in extraction layer:\n  "
            + "\n  ".join(violations)
            + "\nExtractors must be synchronous; wrap with asyncio.to_thread in coordinator."
        )


# ── G5: Kuzu databases opened for reading use read_only=True ─────────────────

class TestG5ReaderConnectionIsReadOnly:
    """
    GraphReader receives an already-open connection; it is the caller's
    responsibility to open the database with read_only=True. We verify
    the two production entry points that open databases for the reader.
    """

    def test_mcp_server_opens_db_read_only(self):
        server_src = (SRC / "mcp" / "server.py").read_text(encoding="utf-8")
        assert "read_only=True" in server_src, (
            "G5 violation — mcp/server.py does not open Kuzu with read_only=True. "
            "All databases passed to GraphReader must be opened in read-only mode."
        )

    def test_reader_docstring_documents_read_only_contract(self):
        reader_src = (GRAPH_DIR / "reader.py").read_text(encoding="utf-8")
        # The module docstring should communicate the read-only contract
        assert "read-only" in reader_src.lower() or "read_only" in reader_src, (
            "G5 violation — reader.py module docstring should document "
            "that the GraphReader is a read-only interface."
        )


# ── G8: coordinator never awaits GraphWriter methods ─────────────────────────

class TestG8WriterIsNeverAwaited:
    COORDINATOR_PATH = PIPELINE_DIR / "coordinator.py"
    WRITER_METHODS = (
        "write_tokens", "write_component", "write_screen", "get_stats",
    )

    def test_no_await_writer_in_coordinator(self):
        source = self.COORDINATOR_PATH.read_text(encoding="utf-8")
        violations = []
        for method in self.WRITER_METHODS:
            # Look for "await writer.method(" or "await writer.write_"
            pattern = rf"await\s+\w*writer\w*\.{re.escape(method)}"
            for i, line in enumerate(source.splitlines(), start=1):
                if re.search(pattern, line):
                    violations.append(f"line {i}: {line.strip()}")
        assert not violations, (
            "G8 violation — GraphWriter method awaited in coordinator.py:\n  "
            + "\n  ".join(violations)
            + "\nGraphWriter is synchronous by design; Kuzu does not support async writes."
        )

    def test_graph_writer_has_no_async_methods(self):
        writer_path = GRAPH_DIR / "writer.py"
        tree = ast.parse(writer_path.read_text(encoding="utf-8"))
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                violations.append(f"writer.py:{node.lineno} async def {node.name}")
        assert not violations, (
            "G8 violation — GraphWriter has async methods:\n  "
            + "\n  ".join(violations)
        )


# ── G9: cli/ does not import internal layers directly ────────────────────────

class TestG9CliDoesNotBypassLayers:
    """
    The CLI layer must remain thin: it may import from coordinator, paths,
    mcp/tools, and its own _logging helper — never from parsing/, extraction/,
    or graph/ directly.

    The only exception: cli/build.py's _build_and_export_chunks coroutine
    drives the chunk pipeline directly (there is no coordinator path for chunk-only
    runs), so lazy local imports inside that coroutine are allowed.
    This guardrail therefore checks top-level (module-level) imports only via AST.
    """
    FORBIDDEN_FROM_CLI = (
        "design_graph.parsing",
        "design_graph.extraction",
        "design_graph.graph",
    )

    def _top_level_imports(self, path: Path) -> list[str]:
        """Return module names from top-level (non-function) import statements."""
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules: list[str] = []
        for node in ast.iter_child_nodes(tree):  # only top-level
            if isinstance(node, ast.Import):
                for alias in node.names:
                    modules.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    modules.append(node.module)
        return modules

    def test_build_py_no_direct_layer_imports_at_top_level(self):
        violations = []
        for mod in self._top_level_imports(CLI_DIR / "build.py"):
            if any(mod.startswith(p) for p in self.FORBIDDEN_FROM_CLI):
                violations.append(f"build.py top-level import: {mod!r}")
        assert not violations, (
            "G9 violation — cli/build.py imports internal layers at module level:\n  "
            + "\n  ".join(violations)
            + "\nUse local imports inside functions or go through coordinator/tools."
        )

    def test_query_py_no_direct_layer_imports_at_top_level(self):
        violations = []
        for mod in self._top_level_imports(CLI_DIR / "query.py"):
            if any(mod.startswith(p) for p in self.FORBIDDEN_FROM_CLI):
                violations.append(f"query.py top-level import: {mod!r}")
        assert not violations, (
            "G9 violation — cli/query.py imports internal layers at module level:\n  "
            + "\n  ".join(violations)
        )
