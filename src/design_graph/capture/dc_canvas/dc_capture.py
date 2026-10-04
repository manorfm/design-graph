"""
Capture for DC canvas prototypes: a canvas of boards whose pages are DC
documents (an <x-dc> template, a logic class and their own bundled assets).
"""

from __future__ import annotations

import logging

from design_graph.capture.base import CaptureResult, ComponentProgress, PrototypeDocument
from design_graph.capture.bundler import Bundle, BundleEntryError, read_bundle
from design_graph.capture.dc_canvas.canvas import Board, read_boards
from design_graph.model.entities import ExtractedComponent, ExtractedScreen

logger = logging.getLogger(__name__)

CAPTURE_NAME = "dc_canvas"


class DcCanvasCapture:
    """Reads a canvas of DC pages — each board one screen."""

    name = CAPTURE_NAME

    def recognizes(self, document: PrototypeDocument) -> bool:
        bundle = read_bundle(document.text)
        return bool(bundle and read_boards(bundle.template))

    async def capture(
        self,
        document: PrototypeDocument,
        *,
        concurrency: int,
        on_component_extracted: ComponentProgress | None = None,
    ) -> CaptureResult:
        bundle = read_bundle(document.text)
        boards = read_boards(bundle.template) if bundle else []
        screens, skipped = [], 0
        for board in boards:
            page = _page_text(bundle, board)
            if page is None:
                skipped += 1
                continue
            screens.append(ExtractedScreen(
                name=board.name, viewport_width=board.width, viewport_height=board.height,
            ))
        return CaptureResult(
            capture=CAPTURE_NAME, components=[], screens=screens, sections={}, tokens=[],
            skipped_entries=skipped,
        )

    def capture_fragment(self, source: str) -> ExtractedComponent | None:
        return None


def _page_text(bundle: Bundle, board: Board) -> str | None:
    try:
        return bundle.entry(board.page_id).decode("utf-8", errors="replace")
    except BundleEntryError as exc:
        logger.warning("dc_canvas: board %r skipped — its page could not be decoded: %s", board.title, exc)
        return None
