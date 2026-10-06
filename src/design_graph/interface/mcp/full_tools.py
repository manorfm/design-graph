"""Uncapped tools: a screen's or component's complete source, styles and texts."""

from __future__ import annotations

from design_graph.model.graph.reader import GraphReader
from design_graph.interface.mcp.markdown import (
    dedupe_styles_by_property,
    named_entity_resolution_error,
    render_referenced_data_value,
)
from design_graph.interface.mcp.notices import full_call


_ASPECTS = ("source", "styles", "texts", "data")


def get_full(
    reader: GraphReader, name: str, aspect: str, screen: str = "", section: str = "", part: object = 1,
) -> str:
    """Whatever another answer shortened, whole: a source (in parts), a style or text list, a component's data."""
    if aspect == "source":
        return get_full_source(reader, name, part)
    if aspect == "styles":
        return get_full_styles(reader, name, screen, section)
    if aspect == "texts":
        return get_full_texts(reader, name, screen, section)
    if aspect == "data":
        return get_full_data(reader, name)
    return f"aspect inválido: {aspect!r}. Use um de: {', '.join(_ASPECTS)}."


# A part of a source is about 5k tokens: enough for any one component,
# small enough that a whole screen's markup never lands in one response.
SOURCE_PART_CHARS = 20_000


MID_LINE_NOTICE = "Esta parte termina no meio de uma linha: a próxima continua a mesma linha."


def get_full_source(reader: GraphReader, name: str, part: object = 1) -> str:
    """A screen's or component's stored source, whole — in parts when it is long."""
    source = reader.get_full_source(name)
    if not source:
        return f"Fonte não disponível para '{name}'. Rode: design-graph --force <proto.html>"

    parts = source_parts(source["source_code"])
    number = _part_number(part, len(parts))
    if number is None:
        return f"Parte inválida: {part!r}. O fonte de '{name}' tem as partes 1 a {len(parts)}."

    lang = source["source_lang"]
    text, mid_line = parts[number - 1]
    header, footer = f"# Fonte completo de {name} ({lang})", ""
    if len(parts) > 1:
        header += f" — parte {number}/{len(parts)}"
        if mid_line:
            footer += f"\n> {MID_LINE_NOTICE}"
        if number < len(parts):
            footer += f"\n> Continua: {full_call('source', name, number + 1)}"
    return f"{header}\n\n```{lang}\n{text}\n```{footer}"


def source_parts(source: str, size: int = SOURCE_PART_CHARS) -> list[tuple[str, bool]]:
    """
    `source` cut into parts of at most `size` characters, each with whether
    it ends in the middle of a line. Parts end at line ends whenever a line
    fits; a line longer than a part is the only thing cut mid-line. Joining
    the parts — with a newline after each one that does not end mid-line —
    gives `source` back exactly.
    """
    parts: list[tuple[str, bool]] = []
    current: list[str] = []
    length = 0
    for line in source.split("\n"):
        if current and length + 1 + len(line) > size:
            parts.append(("\n".join(current), False))
            current, length = [], 0
        while len(line) > size:
            if current:
                parts.append(("\n".join(current), False))
                current, length = [], 0
            parts.append((line[:size], True))
            line = line[size:]
        length += len(line) + (1 if current else 0)
        current.append(line)
    parts.append(("\n".join(current), False))
    return parts


def _part_number(part: object, total: int) -> int | None:
    try:
        number = int(part)
    except (TypeError, ValueError):
        return None
    return number if 1 <= number <= total else None


def get_full_styles(reader: GraphReader, name: str, screen: str, section: str) -> str:
    """
    Uncapped style list — the "source" aspect's equivalent for styles.

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
    Uncapped text list — the "styles" aspect's equivalent for texts.

    get_section/get_screen_full/get_component_spec/get_component_full
    all slice their text list for display ("+N mais" with no way back)
    even though the reader already returns every text row. Renders that same
    data without the display slice — no new query, just no truncation
    (mirrors the styles aspect's C36 fix; see docs/changes/C38).
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


def get_full_data(reader: GraphReader, name: str) -> str:
    """
    Uncapped referenced-module-data — the styles/texts aspects' equivalent for a component's referenced_data (see
    extraction/module_data_extractor.py, docs/changes/C39).

    get_component_spec/get_component/get_component_full/get_screen_full
    all slice each referenced constant's own entries for display
    ("+N mais" with no way back) even though the reader already returns
    every entry. Renders that same data without the slice — no new
    query, just no truncation.
    """
    resolution = reader.resolve_named_entity(name)
    error = named_entity_resolution_error(name, resolution)
    if error:
        return error
    assert resolution.entity is not None
    if resolution.entity.kind == "screen":
        return (
            f"'{resolution.entity.name}' é uma tela; dados referenciados de módulo "
            "ainda só estão disponíveis para componentes."
        )
    spec = reader.get_component_spec(resolution.entity.name)
    if not spec:
        return f"Componente '{resolution.entity.name}' não encontrado."
    referenced_data = spec.get("referenced_data") or {}
    if not referenced_data:
        return (
            f"Nenhum dado referenciado encontrado para o componente '{spec['c.name']}' "
            "(nenhuma constante de módulo é referenciada pelo nome no corpo dele)."
        )
    lines = [f"# Dados referenciados completos: {spec['c.name']}\n"]
    for const_name, entries in sorted(referenced_data.items()):
        items = list(entries.items()) if isinstance(entries, dict) else list(enumerate(entries))
        lines.append(f"## {const_name}")
        lines.extend(f"- `{key}`: `{render_referenced_data_value(value)}`" for key, value in items)
        lines.append("")
    return "\n".join(lines)
