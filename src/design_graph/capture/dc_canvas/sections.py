"""
The blocks of a DC page: below the chain of single wrappers a page starts
with, each child is a block — except the main area, whose own children are
the blocks a reader sees.
"""

from __future__ import annotations

from typing import Callable

from bs4 import Tag

from design_graph.capture.dc_canvas.template import (
    SOURCE_LANG,
    element_children,
    element_paths,
    hint_texts,
    inline_styles,
    parse_markup,
    tag_of,
    visible_texts,
)
from design_graph.model.entities import DetectionMethod, ExtractedSection, StyleEntry

_SEMANTIC_NAMES = {
    "aside": "Sidebar", "nav": "Navigation", "header": "Header", "footer": "Footer", "section": "Section",
}
_HEADINGS = ("h1", "h2", "h3")
_MAX_NAME_CHARS = 40


def page_sections(
    screen: str, blocks: list[Tag], components_in: Callable[[Tag], list[str]],
) -> list[ExtractedSection]:
    """One section per block, referencing the components found inside it."""
    sections, used = [], set()
    for index, block in enumerate(blocks):
        name = _unique(block_name(block, index), used)
        sections.append(ExtractedSection.create(
            screen=screen, name=name, styles=inline_styles(block), component_refs=components_in(block),
            texts=[*visible_texts(block), *hint_texts(block)], source_code=str(block),
            element_styles=[
                StyleEntry.create(path, prop, value)
                for path, element in element_paths(block)
                for prop, value in inline_styles(element).items()
            ],
            detection_method=DetectionMethod.SEMANTIC if tag_of(block) in _SEMANTIC_NAMES
            else DetectionMethod.STRUCTURAL,
            source_lang=SOURCE_LANG,
        ))
    return sections


def page_styles(blocks: list[Tag]) -> list[StyleEntry]:
    """The styles of a page's own elements: the wrappers around its blocks, by path from the page root."""
    if not blocks:
        return []
    root = next(parent for parent in blocks[0].parents if parent.parent is None)
    around = {id(ancestor) for block in blocks for ancestor in block.parents}
    return [
        StyleEntry.create(path, prop, value)
        for path, element in element_paths(root) if id(element) in around
        for prop, value in inline_styles(element).items()
    ]


def page_blocks(markup: str) -> list[Tag]:
    return _blocks(parse_markup(markup))


def _blocks(container: Tag) -> list[Tag]:
    node, children = container, element_children(container)
    while len(children) == 1:
        node, children = children[0], element_children(children[0])
    if not children:
        return [] if node is container else [node]
    blocks: list[Tag] = []
    for child in children:
        blocks.extend(_blocks(child) if tag_of(child) == "main" else [child])
    return blocks


def block_name(block: Tag, index: int) -> str:
    """What a reader calls a block: its label, its heading, its semantic role or the copy it opens with."""
    if block.get("aria-label"):
        return block["aria-label"].strip()
    heading = next((h for h in block.find_all(True) if tag_of(h) in _HEADINGS), None)
    heading_text = _first_wordy(visible_texts(heading)) if heading else None
    if heading_text:
        return _shortened(heading_text)
    if tag_of(block) in _SEMANTIC_NAMES:
        return _SEMANTIC_NAMES[tag_of(block)]
    text = _first_wordy(visible_texts(block))
    return _shortened(text) if text else f"Bloco {index + 1}"


def _first_wordy(texts: list[str]) -> str | None:
    """The first text that has words — never a bare figure like "60%+"."""
    return next((t for t in texts if any(ch.isalpha() for ch in t)), None)


def _shortened(text: str) -> str:
    if len(text) <= _MAX_NAME_CHARS:
        return text
    return text[:_MAX_NAME_CHARS].rsplit(" ", 1)[0].rstrip(" ,;:—-") + "…"


def _unique(name: str, used: set[str]) -> str:
    candidate, n = name, 2
    while candidate in used:
        candidate, n = f"{name} ({n})", n + 1
    used.add(candidate)
    return candidate
