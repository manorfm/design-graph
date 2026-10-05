"""Uncapped tools: a screen's or component's complete source, styles and texts."""

from __future__ import annotations

from design_graph.model.graph.reader import GraphReader
from design_graph.interface.mcp.markdown import dedupe_styles_by_property, named_entity_resolution_error


# A page of source is about 5k tokens: enough for any one component, small
# enough that a whole page's markup never lands in one response.
SOURCE_PAGE_CHARS = 20_000


def get_full_source(reader: GraphReader, name: str, page: object = 1) -> str:
    """A screen's or component's stored source, whole — in pages when it is long."""
    source = reader.get_full_source(name)
    if not source:
        return f"Fonte não disponível para '{name}'. Rode: design-graph --force <proto.html>"

    pages = source_pages(source["source_code"])
    number = _page_number(page, len(pages))
    if number is None:
        return f"Página inválida: {page!r}. O fonte de '{name}' tem as páginas 1 a {len(pages)}."

    lang = source["source_lang"]
    header, footer = f"# Fonte completo de {name} ({lang})", ""
    if len(pages) > 1:
        header += f" — página {number}/{len(pages)}"
        if number < len(pages):
            footer += f"\n> Continua: get_full_source('{name}', page={number + 1})"
    return f"{header}\n\n```{lang}\n{pages[number - 1]}\n```{footer}"


def source_pages(source: str, size: int = SOURCE_PAGE_CHARS) -> list[str]:
    """
    `source` cut into pages of at most `size` characters, at line ends when
    a line fits — joining the pages with newlines gives `source` back, except
    that a line longer than a page is split across pages with no separator.
    """
    pages: list[str] = []
    current: list[str] = []
    length = 0
    for line in source.split("\n"):
        if current and length + 1 + len(line) > size:
            pages.append("\n".join(current))
            current, length = [], 0
        while len(line) > size:
            if current:
                pages.append("\n".join(current))
                current, length = [], 0
            pages.append(line[:size])
            line = line[size:]
        length += len(line) + (1 if current else 0)
        current.append(line)
    pages.append("\n".join(current))
    return pages


def _page_number(page: object, total: int) -> int | None:
    try:
        number = int(page)
    except (TypeError, ValueError):
        return None
    return number if 1 <= number <= total else None


def get_full_styles(reader: GraphReader, name: str, screen: str, section: str) -> str:
    """
    Uncapped style list — the get_full_source equivalent for styles.

    The reader already returns every style row; get_section/
    get_screen_full/get_component_spec only ever slice it for display
    ("+N mais" with no way back). This renders the same reader data
    without the slice — no new query, just no truncation (see
    docs/changes/C36). For name=, also covers @media-scoped styles
    (docs/changes/C41) — get_component_spec is the only other place
    that surfaces them, and it truncates each condition's own table at
    12 rows with no way back, same as the unconditional states.
    """
    if screen and section:
        sec = reader.get_section(screen, section)
        if not sec:
            return f"Seção '{section}' não encontrada em '{screen}'."
        if not sec["styles_by_element"]:
            return f"Nenhum estilo encontrado para a seção '{sec['name']}'."
        lines = [f"# Estilos completos: {sec['name']} (em {screen})\n"]
        for selector, raw_styles in sorted(sec["styles_by_element"].items()):
            lines.append(f"## {selector}")
            lines.append("| Propriedade | Valor |")
            lines.append("|---|---|")
            for s in dedupe_styles_by_property(raw_styles):
                lines.append(f"| {s['property']} | {s['value']} |")
            lines.append("")
        return "\n".join(lines)

    if name:
        resolution = reader.resolve_named_entity(name)
        if resolution.is_ambiguous:
            return named_entity_resolution_error(name, resolution) or ""
        if resolution.entity is None:
            # A CSS class is not a graph entity, so it is intentionally
            # checked only after the named-entity resolver found none.
            class_styles = reader.find_styles_by_class(name)
            if not class_styles:
                return f"Nome '{name}' não encontrado. Use search('{name}') para explorar."
            lines = [f"# Estilos completos: .{name}\n", "| Propriedade | Valor |", "|---|---|"]
            lines.extend(f"| {s['property']} | {s['value']} |" for s in class_styles)
            return "\n".join(lines)

        if resolution.entity.kind == "screen":
            return (
                f"'{resolution.entity.name}' é uma tela. Informe também `section` para obter "
                "os estilos completos de uma seção."
            )
        spec = reader.get_component_spec(resolution.entity.name)
        if not spec:
            return f"Componente '{resolution.entity.name}' não encontrado."
        styles_by_state = spec.get("styles_by_state") or {}
        responsive_by_media = spec.get("responsive_styles_by_media") or {}
        if not styles_by_state and not responsive_by_media:
            return f"Nenhum estilo encontrado para o componente '{spec['c.name']}'."
        lines = [f"# Estilos completos: {spec['c.name']}\n"]
        for state, raw_styles in sorted(styles_by_state.items()):
            lines.append(f"## Estado: {state}")
            lines.append("| Propriedade | Valor |")
            lines.append("|---|---|")
            for s in dedupe_styles_by_property(raw_styles):
                lines.append(f"| {s['property']} | {s['value']} |")
            lines.append("")
        if responsive_by_media:
            # Same C35 rule get_component_spec already applies: a
            # @media-scoped value is never the component's actual
            # default — kept in its own section, labeled by condition,
            # never merged into the states above.
            lines.append("## Estilos responsivos")
            lines.append(
                "> Valores abaixo só se aplicam sob a condição `@media` indicada — "
                "não confundir com o valor default acima.\n"
            )
            for media, raw_styles in sorted(responsive_by_media.items()):
                lines.append(f"### `@media {media}`")
                lines.append("| Propriedade | Valor |")
                lines.append("|---|---|")
                for s in dedupe_styles_by_property(raw_styles):
                    lines.append(f"| {s['property']} | {s['value']} |")
                lines.append("")
        return "\n".join(lines)

    return "Informe `name` (componente) ou `screen` + `section` (seção)."


def get_full_texts(reader: GraphReader, name: str, screen: str, section: str) -> str:
    """
    Uncapped text list — the get_full_styles equivalent for texts.

    get_section/get_screen_full/get_component_spec/get_component_full
    all slice their text list for display ("+N mais" with no way back)
    even though the reader already returns every text row. Renders that same
    data without the display slice — no new query, just no truncation
    (mirrors get_full_styles's C36 fix; see docs/changes/C38).
    """
    if screen and section:
        sec = reader.get_section(screen, section)
        if not sec:
            return f"Seção '{section}' não encontrada em '{screen}'."
        if not sec["texts"]:
            return f"Nenhum texto encontrado para a seção '{sec['name']}'."
        lines = [f"# Textos completos: {sec['name']} (em {screen})\n"]
        lines.extend(f'- "{t}"' for t in sec["texts"])
        return "\n".join(lines)

    if name:
        resolution = reader.resolve_named_entity(name)
        error = named_entity_resolution_error(name, resolution)
        if error:
            return error
        assert resolution.entity is not None
        if resolution.entity.kind == "screen":
            screen = reader.get_screen_texts(resolution.entity.name)
            if not screen or not screen["texts"]:
                return f"Nenhum texto encontrado para a tela '{resolution.entity.name}'."
            lines = [f"# Textos completos: {screen['name']}\n"]
            lines.extend(
                f'- "{text["content"]}" ({text["text_type"]}; {text["source"]})'
                for text in screen["texts"]
            )
            return "\n".join(lines)

        spec = reader.get_component_spec(resolution.entity.name)
        if not spec:
            return f"Componente '{resolution.entity.name}' não encontrado."
        if not spec.get("texts"):
            return f"Nenhum texto encontrado para o componente '{spec['c.name']}'."
        lines = [f"# Textos completos: {spec['c.name']}\n"]
        lines.extend(
            f'- "{t.get("t.content")}" ({t.get("t.text_type")})' for t in spec["texts"]
        )
        return "\n".join(lines)

    return "Informe `name` (componente) ou `screen` + `section` (seção)."
