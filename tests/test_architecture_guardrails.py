"""
Architecture guardrail tests (G1–G12).

These tests enforce the layered dependency rules defined in the project's
backlog.md and docs/spec/00-overview.md. They run as part of the normal
test suite so a CI failure gives immediate feedback on which rule was broken.

G1  capture/html_prototype/parsing/    must not import its extraction/, graph/, or mcp/
G2  capture/html_prototype/extraction/ must not import from graph/ or mcp/
G3  model/graph/reader.py must not contain write statements (CREATE/DELETE/MERGE)
G4  extraction/ functions must be synchronous — async only in coordinator
G5  GraphReader connection must open with read_only=True
G6  FunctionBoundary list must have non-overlapping intervals (covered by T03)
G7  chunk_id values must match [a-z0-9_]+ (covered by T16)
G8  GraphWriter methods must not be awaited in coordinator.py
G9  only the pipeline writes the graph — interfaces never import the writer
G10 plain_html_component_extractor must not import from graph/ or mcp/
    (it is an extraction-layer module — same rules as G2)
G12 format-specific code lives inside capture/, reached from outside only
    through capture.base and capture.registry
G13 model/ depends on nothing else in the package
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

# ── project root relative paths ───────────────────────────────────────────────

SRC = Path(__file__).parent.parent / "src" / "design_graph"
PARSING_DIR    = SRC / "capture" / "html_prototype" / "parsing"
EXTRACTION_DIR = SRC / "capture" / "html_prototype" / "extraction"
GRAPH_DIR      = SRC / "model" / "graph"
PIPELINE_DIR   = SRC / "pipeline"
CLI_DIR        = SRC / "interface" / "cli"


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
        "design_graph.capture.html_prototype.extraction",
        "design_graph.model.graph",
        "design_graph.interface.mcp",
        "design_graph.pipeline",
    )

    def test_no_parsing_module_imports_extraction(self):
        violations = self._collect_violations("design_graph.capture.html_prototype.extraction")
        assert not violations, self._fmt(violations)

    def test_no_parsing_module_imports_graph(self):
        violations = self._collect_violations("design_graph.model.graph")
        assert not violations, self._fmt(violations)

    def test_no_parsing_module_imports_mcp(self):
        violations = self._collect_violations("design_graph.interface.mcp")
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
                if mod.startswith("design_graph.model.graph"):
                    violations.append(f"{f.name}: imports {mod!r}")
        assert not violations, (
            "G2 violation(s) — extraction/ imports from graph/:\n  "
            + "\n  ".join(violations)
        )

    def test_no_extraction_module_imports_mcp(self):
        violations = []
        for f in _py_files(EXTRACTION_DIR):
            for mod in _imports_in_file(f):
                if mod.startswith("design_graph.interface.mcp"):
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
            + "\nAll write operations must live in model/graph/writer.py."
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
        self._check_file(CLI_DIR / "chunk_export.py", allowed=set())

    def test_no_async_functions_in_prop_extractor(self):
        self._check_file(EXTRACTION_DIR / "prop_extractor.py", allowed=set())

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
        server_src = (SRC / "interface" / "mcp" / "server.py").read_text(encoding="utf-8")
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


# ── G10: plain_html_component_extractor respects extraction layer rules ───────

class TestG10PlainHtmlExtractorLayerIsolation:
    """
    plain_html_component_extractor.py is an extraction-layer module.
    Same isolation rules as G2: must not import from graph/ or mcp/.
    """
    EXTRACTOR_PATH = EXTRACTION_DIR / "plain_html_component_extractor.py"
    FORBIDDEN = ("design_graph.model.graph", "design_graph.interface.mcp")

    def test_no_graph_imports_at_module_level(self):
        violations = []
        for mod in _imports_in_file(self.EXTRACTOR_PATH):
            if any(mod.startswith(p) for p in self.FORBIDDEN):
                violations.append(f"plain_html_component_extractor.py: imports {mod!r}")
        assert not violations, (
            "G10 violation — plain_html_component_extractor imports from forbidden layer:\n  "
            + "\n  ".join(violations)
        )

    def test_file_exists(self):
        assert self.EXTRACTOR_PATH.exists(), (
            "G10 expectation: plain_html_component_extractor.py must exist in extraction/"
        )


# ── G9: only the pipeline writes the graph ───────────────────────────────────

class TestG9OnlyThePipelineWritesTheGraph:
    """
    Interfaces (CLI, MCP) read the model; building a graph goes through the
    pipeline, which owns the one atomic write session. No interface may open
    a writer of its own.
    """

    WRITER_MODULES = ("design_graph.model.graph.writer", "design_graph.model.graph.schema")

    def test_interfaces_never_import_the_graph_writer(self):
        violations = [
            f"{_module_name(path)}: imports {mod!r}"
            for directory in (CLI_DIR, SRC / "interface" / "mcp")
            for path in directory.rglob("*.py")
            for mod in _imports_in_file(path)
            if mod.startswith(self.WRITER_MODULES)
        ]
        assert not violations, "G9 violation(s):\n  " + "\n  ".join(violations)


# ── G12: capture/ is sealed behind its contract ──────────────────────────────

CAPTURE_DIR = SRC / "capture"
CAPTURE_CONTRACT = ("design_graph.capture.base", "design_graph.capture.registry")


def _module_name(path: Path) -> str:
    return "design_graph." + ".".join(path.relative_to(SRC).with_suffix("").parts)


class TestG12CaptureIsSealed:
    """
    Every format-specific module lives inside capture/, and the rest of the
    system reaches a capture only through its contract (capture.base) and the
    registry — so adding a format never touches code outside capture/.
    """

    def test_format_specific_packages_live_inside_capture(self):
        stray = [name for name in ("parsing", "extraction") if (SRC / name).exists()]
        assert not stray, f"G12 violation — format-specific packages outside capture/: {stray}"

    def test_only_the_contract_is_imported_from_outside_capture(self):
        violations = []
        for path in SRC.rglob("*.py"):
            relative = path.relative_to(SRC).as_posix()
            if relative.startswith("capture/"):
                continue
            for mod in _imports_in_file(path):
                if mod.startswith("design_graph.capture.") and mod not in CAPTURE_CONTRACT:
                    violations.append(f"{relative}: imports {mod!r}")
        assert not violations, "G12 violation(s):\n  " + "\n  ".join(violations)

    def test_capture_never_imports_storage_pipeline_or_interfaces(self):
        forbidden = ("design_graph.model.graph", "design_graph.interface.mcp", "design_graph.interface.cli", "design_graph.pipeline")
        violations = [
            f"{_module_name(path)}: imports {mod!r}"
            for path in CAPTURE_DIR.rglob("*.py")
            for mod in _imports_in_file(path)
            if mod.startswith(forbidden)
        ]
        assert not violations, "G12 violation(s):\n  " + "\n  ".join(violations)


# ── G13: model/ is the stable centre ──────────────────────────────────────────

MODEL_DIR = SRC / "model"


class TestG13ModelIsTheCentre:
    """
    model/ holds the design entities and their graph storage. Captures,
    the pipeline and the interfaces all depend on it — it depends on none of
    them, so none of them can force it to change.
    """

    def test_shared_core_package_is_dissolved_into_model(self):
        assert not (SRC / "core").exists(), "G13 violation — core/ still exists; its entities belong in model/"
        assert not (SRC / "graph").exists(), "G13 violation — graph/ still exists; storage belongs in model/"

    def test_model_never_imports_capture_pipeline_or_interfaces(self):
        forbidden = ("design_graph.capture", "design_graph.pipeline", "design_graph.interface.mcp", "design_graph.interface.cli")
        violations = [
            f"{_module_name(path)}: imports {mod!r}"
            for path in MODEL_DIR.rglob("*.py")
            for mod in _imports_in_file(path)
            if mod.startswith(forbidden)
        ]
        assert not violations, "G13 violation(s):\n  " + "\n  ".join(violations)


# ── G14: interfaces are thin adapters over the model ──────────────────────────

INTERFACE_DIR = SRC / "interface"


class TestG14InterfacesAreThinAdapters:
    """
    Every way of using design-graph (CLI, MCP server, …) lives in interface/
    and reaches the rest only through the model, the build pipeline and the
    shared workspace configuration — so a new interface is one new package.
    """

    ALLOWED = (
        "design_graph.interface",
        "design_graph.model",
        "design_graph.pipeline",
        "design_graph.paths",
        "design_graph.workspace",
    )

    def test_interfaces_live_inside_interface(self):
        stray = [name for name in ("mcp", "cli") if (SRC / name).exists()]
        assert not stray, f"G14 violation — interface packages outside interface/: {stray}"

    def test_interfaces_import_only_model_pipeline_and_config(self):
        violations = [
            f"{_module_name(path)}: imports {mod!r}"
            for path in INTERFACE_DIR.rglob("*.py")
            for mod in _imports_in_file(path)
            if mod.startswith("design_graph") and not mod.startswith(self.ALLOWED)
        ]
        assert not violations, "G14 violation(s):\n  " + "\n  ".join(violations)


# ── G15: the model speaks design, not a source format ─────────────────────────

class TestG15ModelHasNoFormatVocabulary:
    """
    No identifier or string the model's code uses may belong to one source
    format (JSX, React, a framework's attribute names) — such knowledge lives
    in the capture that reads that format. Docstrings and comments may still
    mention formats as examples.
    """

    FORMAT_WORDS = re.compile(r"jsx|react|classname|dclogic", re.IGNORECASE)

    @staticmethod
    def _code_words(path: Path) -> list[tuple[int, str]]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str)
        }
        words: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                words.append((node.lineno, node.id))
            elif isinstance(node, ast.Attribute):
                words.append((node.lineno, node.attr))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                words.append((node.lineno, node.name))
            elif isinstance(node, ast.arg):
                words.append((node.lineno, node.arg))
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                words.append((node.lineno, node.value))
        return words

    def test_model_code_carries_no_format_vocabulary(self):
        violations = [
            f"{path.relative_to(SRC)}:{line}: {word[:60]!r}"
            for path in MODEL_DIR.rglob("*.py")
            for line, word in self._code_words(path)
            if self.FORMAT_WORDS.search(word)
        ]
        assert not violations, "G15 violation(s):\n  " + "\n  ".join(violations)


# ── G16: interfaces speak design, not a source format ─────────────────────────

class TestG16InterfacesHaveNoFormatVocabulary:
    """
    What an agent or a user reads — tool names, descriptions, Markdown, CLI
    flags — never assumes a source format; the language of a stored source
    comes from the graph (source_lang), not from the interface.
    """

    def test_interface_code_carries_no_format_vocabulary(self):
        g15 = TestG15ModelHasNoFormatVocabulary
        violations = [
            f"{path.relative_to(SRC)}:{line}: {word[:60]!r}"
            for path in INTERFACE_DIR.rglob("*.py")
            for line, word in g15._code_words(path)
            if g15.FORMAT_WORDS.search(word)
        ]
        assert not violations, "G16 violation(s):\n  " + "\n  ".join(violations)
