"""
Deduplication of inline SVG icon markup out of a component's raw JSX.

extract_icons() runs before sanitize_jsx(): it finds every <svg>...</svg> (or
self-closing <svg .../>) block, replaces it with a short {[icon:id]} marker,
and returns the IconAsset each marker stands for. The same icon reused
anywhere — twice in one component, or once each in a hundred — always hashes
to the same id (see IconAsset.create), so the graph stores its markup once
no matter how many places render it. GraphReader expands the marker back to
the full markup on read (see graph.reader.GraphReader._resolve_icons).
"""

from __future__ import annotations

from collections.abc import Iterator

from design_graph.core.models import IconAsset
from design_graph.core.patterns import RE_SVG_CLOSE_TAG, RE_SVG_OPEN_TAG


def extract_icons(jsx: str) -> tuple[str, list[IconAsset]]:
    """
    Replace every <svg> block in `jsx` with its {[icon:id]} marker.

    Returns the rewritten text and the icons referenced, in source order
    (with a repeated entry for each occurrence of a reused icon — callers
    that want the deduplicated set should key by IconAsset.id).
    """
    spans = list(_iter_svg_spans(jsx))
    if not spans:
        return jsx, []

    icons: list[IconAsset] = []
    pieces: list[str] = []
    cursor = 0
    for start, end in spans:
        icon = IconAsset.create(jsx[start:end])
        icons.append(icon)
        pieces.append(jsx[cursor:start])
        pieces.append(str(icon))
        cursor = end
    pieces.append(jsx[cursor:])
    return "".join(pieces), icons


def _iter_svg_spans(text: str) -> Iterator[tuple[int, int]]:
    """
    Yield (start, end) spans of top-level <svg>...</svg> or self-closing
    <svg/> blocks, tracking nesting depth so a sprite's inner <svg> (inside
    <defs>) doesn't end the span early at its own </svg>.

    An <svg> with no matching close tag is not yielded — the rest of the
    text is left untouched rather than guessed at.
    """
    pos = 0
    while True:
        open_match = RE_SVG_OPEN_TAG.search(text, pos)
        if open_match is None:
            return
        if open_match.group("self_close"):
            yield open_match.start(), open_match.end()
            pos = open_match.end()
            continue

        depth = 1
        cursor = open_match.end()
        while depth > 0:
            next_open = RE_SVG_OPEN_TAG.search(text, cursor)
            next_close = RE_SVG_CLOSE_TAG.search(text, cursor)
            if next_close is None:
                return  # unbalanced — stop scanning rather than guess
            if next_open and next_open.start() < next_close.start():
                cursor = next_open.end()
                if not next_open.group("self_close"):
                    depth += 1
            else:
                depth -= 1
                cursor = next_close.end()

        yield open_match.start(), cursor
        pos = cursor
