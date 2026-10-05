"""Notices that tell an agent what a response leaves out and how to recover it."""

from __future__ import annotations

def truncation_notice(
    total: int, shown: int, recoverable_via: str | None = None, tool: str = "get_full_styles",
) -> str | None:
    """
    Return a Markdown blockquote notice when a list was cut, else None.

    recoverable_via: when a real escape hatch exists for what got cut
    (styles via get_full_styles, texts via get_full_texts — see
    docs/changes/C36 and C38), the exact call to make — same "never
    truncate without naming the way back" convention already used by
    CappedSource.notice for source_code/component
    truncation. None (a caller with no escape hatch at all) keeps the
    notice as it was before this parameter existed.

    tool: which uncapped tool recovers this particular list — callers pass
    "get_full_texts" for text tables, default "get_full_styles" for style
    tables, so the same helper serves both without duplicating this
    formatting.
    """
    if total <= shown:
        return None
    notice = f"> ... +{total - shown} mais"
    if recoverable_via:
        notice += f" — chame `{tool}({recoverable_via})` para a lista completa"
    return notice


class CappedSource(str):
    """
    A stored source capped to a display limit, aware of its own cut.

    Mirrors PropDefault (model/entities.py): a fact about the value — whether it
    was cut, and by how much — lives on the value itself instead of being
    recomputed from a raw length comparison at every render site.
    """

    __slots__ = ("full_length",)

    def __new__(cls, raw: str, limit: int) -> CappedSource:
        obj = str.__new__(cls, raw[:limit])
        obj.full_length = len(raw)
        return obj

    @property
    def was_cut(self) -> bool:
        return self.full_length > len(self)

    def notice(self, recoverable_via: str | None) -> str | None:
        """
        A Markdown blockquote naming what was cut, or None when nothing was.

        recoverable_via: name to pass get_full_source() when that tool can
        recover the rest. get_full_source lifts this display limit, not any
        simplification the capture already applied to the stored source —
        it only matches screens and components, so callers rendering a
        section pass None instead of a false lead.
        """
        if not self.was_cut:
            return None
        cut = self.full_length - len(self)
        if recoverable_via:
            return f"> ... +{cut} caracteres (chame get_full_source('{recoverable_via}') para o fonte completo)"
        return f"> ... +{cut} caracteres cortados"


_MIN_SOURCE_LENGTH_FOR_SCREEN_STRUCTURE_GAP = 200


class ScreenStructureGap:
    """
    True when a screen's own source is non-trivial but the section/component
    extraction cascade produced nothing to show it — no comment marker, no
    padding-styled div, and no raw-markup list gave section_extractor
    anything to anchor a Section on, and the screen references no Component
    either. Only meaningful where Sections and Components are already known
    to be empty for this screen — get_screen_full checks that before
    constructing this, the same call-site pattern StyleExtractionGap uses.
    """

    __slots__ = ("exists",)

    def __init__(self, source_code: str) -> None:
        self.exists = len(source_code or "") >= _MIN_SOURCE_LENGTH_FOR_SCREEN_STRUCTURE_GAP

    def notice(self, recoverable_via: str) -> str | None:
        if not self.exists:
            return None
        return (
            f"> ⚠ Nenhuma estrutura extraída para '{recoverable_via}' — containers, "
            f"classes, textos e ícones condicionais podem estar invisíveis aqui. "
            f"Chame get_full_source('{recoverable_via}') para o fonte completo."
        )


class StyleExtractionGap:
    """
    True when a component's source declares inline styles (a fact its capture
    recorded) but the graph has no structured Style rows for it — usually because every value is a runtime
    expression (`hsl(${hue}...)`, a ternary, a prop reference) rather than a
    literal the extractor can store. Only meaningful where styles are
    already known to be empty: an empty Styles section alone can't tell
    "no styling" apart from this case.
    """

    __slots__ = ("exists",)

    def __init__(self, declares_inline_styles: bool) -> None:
        self.exists = declares_inline_styles

    def notice(self) -> str | None:
        if not self.exists:
            return None
        return (
            "> No structured styles extracted — this component's styling is "
            "likely computed at runtime (template literals, ternaries); read "
            "the source for actual values."
        )


def source_block_lines(
    source_code: str, lang: str, limit: int, recoverable_via: str | None, heading: str | None = None,
) -> list[str]:
    """
    A stored source as a fenced block in its own language, capped to `limit`,
    followed by a notice when the cap cut it. `heading` titles the block.
    """
    capped = CappedSource(source_code, limit)
    lines = ([heading] if heading else []) + [f"```{lang}", capped, "```"]
    notice = capped.notice(recoverable_via=recoverable_via)
    return lines + ([notice] if notice else [])

