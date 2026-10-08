"""
Capture for DC canvas prototypes: a canvas of boards whose pages are DC
documents (an <x-dc> template, a logic class and their own bundled assets).
"""

from __future__ import annotations

import logging
from dataclasses import replace

from bs4 import Tag

from design_graph.capture.base import CaptureResult, ComponentProgress, PrototypeDocument
from design_graph.capture.bundler import Bundle, BundleEntryError, read_bundle
from design_graph.capture.dc_canvas.canvas import Board, read_boards
from design_graph.capture.dc_canvas.page import DcPage, read_page
from design_graph.capture.dc_canvas.components import element_actions, fragment_component, infer_components
from design_graph.capture.dc_canvas.instances import Definition, definition_of, fitting_occurrences, replace_with_instances
from design_graph.capture.dc_canvas.logic import list_member, literal_lists, member_expression, state_defaults
from design_graph.capture.dc_canvas.sections import page_blocks, page_root, page_sections, page_styles
from design_graph.capture.dc_canvas.screens import Variant, links, variants
from design_graph.capture.dc_canvas.template import (
    SOURCE_LANG, drop_authoring_hints, element_children, element_paths, parse_markup, rendered_descendants,
)
from design_graph.capture.html_prototype.parsing.css_class_resolver import extract_tag_pseudo_rules
from design_graph.capture.dc_canvas.tokens import extract_canvas_tokens
from design_graph.model.entities import ComponentProp, ExtractedComponent, ExtractedScreen, State

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
        blocks = {board.name: page_blocks(pages[board.page_id].markup) for board in boards}
        lists_by_screen = {board.name: literal_lists(pages[board.page_id].logic) for board in boards}
        logic_by_screen = {board.name: pages[board.page_id].logic for board in boards}
        found = infer_components(
            blocks,
            tag_rules=extract_tag_pseudo_rules("\n".join(dict.fromkeys(p.styles for p in pages.values()))),
            loop_data=lambda screen, name: lists_by_screen[screen].get(name),
            handler_of=lambda screen, key: member_expression(logic_by_screen[screen], key),
            on_component=on_component_extracted,
        )
        screens = [_screen(board, pages[board.page_id], boards, board_variants) for board in boards]
        sections = {name: page_sections(name, screen_blocks, found.outermost_in) for name, screen_blocks in blocks.items()}
        definitions = _definitions(blocks, found.name_of)
        components = [_defined(component, definitions.get(component.name), found.name_of, definitions)
                      for component in found.components]
        board_page = {board.name: pages[board.page_id] for board in boards}
        for screen in screens:
            screen.sections_count = len(sections[screen.name])
            screen.styles = page_styles(blocks[screen.name])
            screen.states = [State.create(screen.name, name, default)
                             for name, default in state_defaults(logic_by_screen[screen.name])]
            screen.actions = element_actions(
                screen.name, element_paths(page_root(blocks[screen.name])) if blocks[screen.name] else [],
                lambda list_name, key, logic=logic_by_screen[screen.name]: list_member(logic, list_name, key),
            )
            screen.component_refs = list(dict.fromkeys(
                ref for block in blocks[screen.name] for ref in found.outermost_in(block)
            ))
        for screen in screens:  # last: swapping occurrences for instances rewrites the parsed pages
            screen.skeleton, instantiated = _skeleton(board_page[screen.name], blocks[screen.name], found.name_of, definitions)
            screen.component_refs = list(dict.fromkeys(screen.component_refs + instantiated))
        return CaptureResult(
            capture=CAPTURE_NAME, components=components, screens=screens, sections=sections,
            tokens=extract_canvas_tokens(list(pages.values())), skipped_entries=skipped,
            resources=list({r.id: r for page in pages.values() for r in page.resources}.values()),
        )

    def capture_fragment(self, source: str) -> ExtractedComponent | None:
        """Read a template fragment — e.g. an implementation to check — as one component."""
        roots = element_children(parse_markup(source))
        return fragment_component(roots[0]) if roots else None


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


def _definitions(blocks: dict[str, list[Tag]], name_of: dict[int, str]) -> dict[str, Definition]:
    """Each component's definition, from every occurrence across the screens, first seen first."""
    occurrences: dict[str, list[Tag]] = {}
    for screen_blocks in blocks.values():
        for element in (e for block in screen_blocks for e in [block, *rendered_descendants(block)]):
            if id(element) in name_of:
                occurrences.setdefault(name_of[id(element)], []).append(element)
    return {name: definition_of(elements) for name, elements in occurrences.items()}


def _defined(
    component: ExtractedComponent, definition: Definition | None,
    name_of: dict[int, str], definitions: dict[str, Definition],
) -> ExtractedComponent:
    """
    The component with its template as source, its slots as props and, as
    children, also what its template renders inside markup of another
    component's other shape — reached by no definition but this one.
    """
    if definition is None:
        return component
    inside = [name for _, name in fitting_occurrences(definition.example, name_of, definitions)] \
        if definition.example is not None else []
    return replace(
        component, source_code=definition.markup,
        props=[ComponentProp.create(component.name, slot, value) for slot, value in definition.slots],
        child_refs=list(dict.fromkeys(component.child_refs + inside)),
    )


def _skeleton(
    page: DcPage, screen_blocks: list[Tag], name_of: dict[int, str], definitions: dict[str, Definition],
) -> tuple[str, list[str]]:
    """The page's source with every component occurrence that fits its definition as an instance tag, and those components."""
    if not screen_blocks:
        return "", []
    root = next(parent for parent in screen_blocks[0].parents if parent.parent is None)
    instantiated = replace_with_instances(root, name_of, definitions)
    drop_authoring_hints(root)
    return page.source_with(str(root)), instantiated


def _screen(board: Board, page: DcPage, boards: list[Board], board_variants: dict[str, Variant]) -> ExtractedScreen:
    variant = board_variants.get(board.name)
    return ExtractedScreen(
        name=board.name,
        title=page.title if page.title not in (board.title, board.name) else "",
        source_code=page.source,
        source_lang=SOURCE_LANG,
        viewport_width=board.width,
        viewport_height=board.height,
        links=links(page, boards, set(board_variants)),
        resource_ids=[resource.id for resource in page.resources],
        variant_of=variant.base if variant else "",
        variant_axis=variant.axis if variant else "",
    )
