"""
The capture contract: how a prototype file of any format becomes design-graph
entities.

A capture knows one family of source formats and nothing beyond the domain
entities it produces — never the graph storage, the MCP server or the CLI.
The pipeline reads the file once (PrototypeDocument), asks the registry which
capture recognizes it, and writes whatever CaptureResult comes back.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from design_graph.model.entities import (
    DesignToken,
    ExtractedComponent,
    ExtractedScreen,
    ExtractedSection,
    TextEntry,
)

# Largest prototype file accepted. Real bundles run to ~15 MB; the cap keeps a
# mistaken path (a disk image, a video) from being read whole into memory.
MAX_PROTOTYPE_BYTES = 256 * 1024 * 1024


class UnsupportedPrototypeError(ValueError):
    """The file cannot be read as a prototype by any registered capture."""


@dataclass(frozen=True)
class PrototypeDocument:
    """A prototype file read once: its path, decoded text and content digest."""

    path: Path
    text: str
    digest: str  # md5 of the raw bytes — the incremental-build identity of the file

    @classmethod
    def read(cls, path: Path) -> "PrototypeDocument":
        if not path.exists():
            raise FileNotFoundError(f"Prototype not found: {path}")
        if not path.is_file():
            raise UnsupportedPrototypeError(f"Prototype path is not a file: {path}")
        size = path.stat().st_size
        if size > MAX_PROTOTYPE_BYTES:
            raise UnsupportedPrototypeError(
                f"Prototype {path.name} is too large ({size} bytes, limit {MAX_PROTOTYPE_BYTES})"
            )
        raw = path.read_bytes()
        return cls(
            path=path,
            text=raw.decode("utf-8", errors="replace"),
            digest=hashlib.md5(raw, usedforsecurity=False).hexdigest(),
        )


@dataclass
class CaptureResult:
    """Everything one capture extracted from one prototype, ready to be written."""

    capture: str
    components: list[ExtractedComponent]
    screens: list[ExtractedScreen]
    sections: dict[str, list[ExtractedSection]]  # screen name → its sections
    tokens: list[DesignToken]
    module_texts: list[TextEntry] = field(default_factory=list)
    skipped_entries: int = 0  # embedded resources that could not be decoded


ComponentProgress = Callable[[str, int, int], None]


class Capture(Protocol):
    """One family of prototype formats the pipeline can read."""

    name: str

    def recognizes(self, document: PrototypeDocument) -> bool: ...

    async def capture(
        self,
        document: PrototypeDocument,
        *,
        concurrency: int,
        on_component_extracted: ComponentProgress | None = None,
    ) -> CaptureResult: ...
