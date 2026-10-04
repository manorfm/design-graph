"""
Capture for DC canvas prototypes: a canvas of boards whose pages are DC
documents (an <x-dc> template, a logic class and their own bundled assets).
"""

from __future__ import annotations

import logging

from design_graph.capture.base import CaptureResult, ComponentProgress, PrototypeDocument
from design_graph.capture.bundler import Bundle, BundleEntryError, read_bundle
from design_graph.capture.dc_canvas.canvas import Board, read_boards
from design_graph.capture.dc_canvas.page import DcPage, read_page
from design_graph.capture.dc_canvas.screens import Variant, links, variants
from design_graph.capture.dc_canvas.tokens import extract_canvas_tokens
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
        boards, pages, skipped = _boards_with_pages(bundle)
        board_variants = variants(boards, pages)
        screens = [
            _screen(board, pages[board.page_id], boards, board_variants)
            for board in boards
        ]
        return CaptureResult(
            capture=CAPTURE_NAME, components=[], screens=screens, sections={},
            tokens=extract_canvas_tokens(list(pages.values())), skipped_entries=skipped,
        )

    def capture_fragment(self, source: str) -> ExtractedComponent | None:
        return None


SOURCE_LANG = "html-template"


def _boards_with_pages(bundle: Bundle | None) -> tuple[list[Board], dict[str, DcPage], int]:
    """The boards whose page could be read, their pages by id, and how many could not."""
    boards, pages, skipped = [], {}, 0
    for board in read_boards(bundle.template) if bundle else []:
        page = _read_board_page(bundle, board)
        if page is None:
            skipped += 1
            continue
        boards.append(board)
        pages[board.page_id] = page
    return boards, pages, skipped


def _read_board_page(bundle: Bundle, board: Board) -> DcPage | None:
    try:
        text = bundle.entry(board.page_id).decode("utf-8", errors="replace")
    except BundleEntryError as exc:
        logger.warning("dc_canvas: board %r skipped — its page could not be decoded: %s", board.title, exc)
        return None
    page = read_page(text)
    if page is None:
        logger.warning("dc_canvas: board %r skipped — its page is not a DC page", board.title)
    return page


def _screen(board: Board, page: DcPage, boards: list[Board], board_variants: dict[str, Variant]) -> ExtractedScreen:
    variant = board_variants.get(board.name)
    return ExtractedScreen(
        name=board.name,
        source_code=page.source,
        source_lang=SOURCE_LANG,
        viewport_width=board.width,
        viewport_height=board.height,
        links=links(page, boards, set(board_variants)),
        variant_of=variant.base if variant else "",
        variant_axis=variant.axis if variant else "",
    )
