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
    truncated_fields_notice and CappedJsx.notice for source_code/component
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


def truncated_fields_notice(
    truncated_fields: str | list[str] | None,
    recoverable_via: str | None = None,
) -> str | None:
    """
    Blockquote warning when extraction hit a MAX_*_PER_COMPONENT cap for one
    or more fields (styles/interactions/texts/classes) on this component.

    Accepts either the raw comma-separated string stored on the Component
    node (get_component/get_component_spec) or the already-split list shape
    used by get_screen_full — same fact, two call sites with different
    intermediate shapes. Without this, an agent reading a "complete-looking"
    spec has no way to tell it was cut, not just short.
    """
    fields = (
        [f for f in truncated_fields.split(",") if f]
        if isinstance(truncated_fields, str)
        else list(truncated_fields or [])
    )
    if not fields:
        return None
    field_list = ", ".join(fields)
    suffix = f" Chame get_full_jsx('{recoverable_via}') para o JSX bruto." if recoverable_via else ""
    return f"> ⚠ Extração truncada em: {field_list} — esta spec pode estar incompleta.{suffix}"


class CappedJsx(str):
    """
    A JSX/markup snippet capped to a display limit, aware of its own cut.

    Mirrors PropDefault (model/entities.py): a fact about the value — whether it
    was cut, and by how much — lives on the value itself instead of being
    recomputed from a raw length comparison at every render site.
    """

    __slots__ = ("full_length",)

    def __new__(cls, raw: str, limit: int) -> CappedJsx:
        obj = str.__new__(cls, raw[:limit])
        obj.full_length = len(raw)
        return obj

    @property
    def was_cut(self) -> bool:
        return self.full_length > len(self)

    def notice(self, recoverable_via: str | None) -> str | None:
        """
        A Markdown blockquote naming what was cut, or None when nothing was.

        recoverable_via: component name to pass get_full_jsx() when that tool
        can recover the rest. get_full_jsx lifts the CappedJsx length limit
        applied here, not the jsx_sanitizer markers already baked into the
        stored snippet — it only matches Component nodes, so callers
        rendering a section pass None instead of a false lead.
        """
        if not self.was_cut:
            return None
        cut = self.full_length - len(self)
        if recoverable_via:
            return f"> ... +{cut} caracteres (chame get_full_jsx('{recoverable_via}') para o JSX completo)"
        return f"> ... +{cut} caracteres cortados"


_MIN_JSX_LENGTH_FOR_SCREEN_STRUCTURE_GAP = 200


class ScreenStructureGap:
    """
    True when a screen's own JSX is non-trivial but the section/component
    extraction cascade produced nothing to show it — no comment marker, no
    padding-styled div, and no raw-markup list gave section_extractor
    anything to anchor a Section on, and the screen references no Component
    either. Only meaningful where Sections and Components are already known
    to be empty for this screen — get_screen_full checks that before
    constructing this, the same call-site pattern StyleExtractionGap uses.
    """

    __slots__ = ("exists",)

    def __init__(self, source_code: str) -> None:
        self.exists = len(source_code or "") >= _MIN_JSX_LENGTH_FOR_SCREEN_STRUCTURE_GAP

    def notice(self, recoverable_via: str) -> str | None:
        if not self.exists:
            return None
        return (
            f"> ⚠ Nenhuma estrutura extraída para '{recoverable_via}' — containers, "
            f"classes, textos e ícones condicionais podem estar invisíveis aqui. "
            f"Chame get_full_jsx('{recoverable_via}') para o JSX bruto."
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
            "the JSX for actual values."
        )
