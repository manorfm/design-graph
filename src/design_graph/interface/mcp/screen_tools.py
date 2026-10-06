"""Screen tools: listing screens and reconstructing one screen, its layout or a section."""

from __future__ import annotations

import json
import logging

from design_graph.model.graph.reader import GraphReader
from design_graph.interface.mcp.markdown import (
    component_lines,
    screen_relation_lines,
    section_style_group_lines,
)
from design_graph.interface.mcp.notices import (
    ScreenStructureGap,
    source_block_lines,
    truncation_notice,
)

logger = logging.getLogger(__name__)


def list_screens(readers: list[tuple[str, GraphReader]]) -> str:
    lines = ["# Telas disponíveis\n"]
    for doc_name, reader in readers:
        screens = reader.list_screens()
        if not screens:
            continue
        lines.append(f"## {doc_name}")
        for s in screens:
            top = ", ".join(s.get("top_components", []))
            variant = f" — variante de {s['variant_of']}" if s.get("variant_of") else ""
            lines.append(f"**{s['name']}** ({s['component_count']} componentes){variant}")
            if top:
                lines.append(f"  → {top}")
        lines.append("")
    return "\n".join(lines) if len(lines) > 1 else "Nenhuma tela encontrada."


def get_screen(reader: GraphReader, name: str) -> str:
    screen = reader.get_screen(name)
    if not screen:
        all_screens = [s["name"] for s in reader.list_screens()]
        return f"Tela '{name}' não encontrada. Disponíveis: {', '.join(all_screens)}"

    lines = [
        f"# Tela: {screen['name']}",
        f"Componentes: {screen['component_count']}  |  Seções: {screen['sections_count']}",
        *screen_relation_lines(screen.get("relations")),
        "",
    ]
    for sec in screen.get("sections", []):
        comp_refs = json.loads(sec.get("sec.components_json") or sec.get("components_json", "[]"))
        lines.append(f"### {sec.get('sec.name') or sec.get('name', '')}")
        if comp_refs:
            lines.append(f"Componentes: {', '.join(comp_refs)}")
    if screen.get("components"):
        lines.append("\n## Todos os componentes")
        by_type: dict[str, list[str]] = {}
        for c in screen["components"]:
            by_type.setdefault(c.get("c.comp_type", "component"), []).append(c.get("c.name", ""))
        for t, names in sorted(by_type.items()):
            lines.append(f"**{t}**: {', '.join(names)}")
    return "\n".join(lines)


def get_screen_full(reader: GraphReader, name: str) -> str:
    """
    Render the complete screen spec as Markdown for AI agent consumption.

    Output structure:
      # Screen heading + counts
      ## Sections — each with styles, component refs, texts and source
      ## Components — each with styles-by-state, tokens, interactions, props, children, source

    Layout data (display, align-items, ...) lives in each component's own
    "Styles — default" table, not a separate section — get_screen_layout
    is the tool for callers who want only the layout summary.
    """
    spec = reader.get_screen_full(name)
    if not spec:
        all_screens = [s["name"] for s in reader.list_screens()]
        return (
            f"Screen '{name}' not found. "
            f"Available: {', '.join(all_screens) or 'none'}"
        )

    lines = [
        f"# Screen: {spec['name']}",
        f"**Components**: {spec['component_count']}  |  **Sections**: {spec['sections_count']}",
        *screen_relation_lines(spec.get("relations")),
        "",
    ]

    if not spec["sections"] and not spec["components"]:
        gap_notice = ScreenStructureGap(spec.get("source_code", "")).notice(
            recoverable_via=spec["name"]
        )
        if gap_notice:
            lines.append(gap_notice)
            lines.append("")

    if spec.get("styles"):
        lines.append("## Page styles\n")
        lines.extend(f"- **{s['element']}** `{s['property']}`: `{s['value']}`" for s in spec["styles"])
        lines.append("")

    if spec["sections"]:
        lines.append("## Sections\n")
        for sec in spec["sections"]:
            lines.extend(_section_lines(spec["name"], sec))

    if spec["components"]:
        lines.append("---\n## Components\n")
        for comp in spec["components"]:
            lines.extend(component_lines(comp, heading=f"### {comp['name']}"))

    logger.debug("tools: get_screen_full(%s) — rendered", spec["name"])
    return "\n".join(lines)


def _section_lines(screen_name: str, sec: dict) -> list[str]:
    lines: list[str] = []
    lines.append(f"### {sec['name']}")
    lines.append(f"*Detection*: {sec['detection_method']}")
    if sec["component_refs"]:
        lines.append(f"**Components**: {', '.join(sec['component_refs'])}")
    if sec["styles_by_element"]:
        lines.append("**Styles**:")
        lines.extend(section_style_group_lines(
            sec["styles_by_element"], recoverable_via=f'screen="{screen_name}", section="{sec["name"]}"',
        ))
    if sec["texts"]:
        for t in sec["texts"][:6]:
            lines.append(f'- "{t}"')
        notice = truncation_notice(
            len(sec["texts"]), 6,
            recoverable_via=f'screen="{screen_name}", section="{sec["name"]}"', aspect="texts",
        )
        if notice:
            lines.append(notice)
    if sec["source_code"]:
        lines.append("")
        lines.extend(source_block_lines(sec["source_code"], sec["source_lang"], 2000, recoverable_via=None))
    lines.append("")
    return lines


def get_screen_layout(reader: GraphReader, name: str) -> str:
    """Return layout profiles for all components on a screen as Markdown."""
    profiles = reader.get_screen_layout(name)
    if not profiles:
        return f"Screen '{name}' not found or has no components with layout data."

    lines = [f"# Layout: {name}\n"]
    for p in profiles:
        lines.append(f"## {p['component_name']}")
        layout_pairs = [
            ("display",          p.get("display")),
            ("position",         p.get("position")),
            ("width",            p.get("width")),
            ("height",           p.get("height")),
            ("padding",          p.get("padding")),
            ("padding-top",      p.get("padding_top")),
            ("padding-right",    p.get("padding_right")),
            ("padding-bottom",   p.get("padding_bottom")),
            ("padding-left",     p.get("padding_left")),
            ("margin",           p.get("margin")),
            ("margin-top",       p.get("margin_top")),
            ("margin-right",     p.get("margin_right")),
            ("margin-bottom",    p.get("margin_bottom")),
            ("margin-left",      p.get("margin_left")),
            ("flex-direction",   p.get("flex_direction")),
            ("align-items",      p.get("align_items")),
            ("justify-content",  p.get("justify_content")),
            ("gap",              p.get("gap")),
            ("overflow",         p.get("overflow")),
            ("z-index",          p.get("z_index")),
        ]
        for css_prop, val in layout_pairs:
            if val is not None:
                lines.append(f"- `{css_prop}`: `{val}`")
        for extra_prop, extra_val in p.get("extra_layout", {}).items():
            lines.append(f"- `{extra_prop}`: `{extra_val}`")
        lines.append("")
    logger.debug("tools: get_screen_layout(%s) — %d components", name, len(profiles))
    return "\n".join(lines)


def get_section(reader: GraphReader, screen: str, section: str) -> str:
    sec = reader.get_section(screen, section)
    if not sec:
        return f"Seção '{section}' não encontrada em '{screen}'."
    lines = [f"# Seção: {sec['name']}  (em {screen})", ""]
    if sec["styles_by_element"]:
        lines.append("## Estilos")
        lines.extend(section_style_group_lines(
            sec["styles_by_element"], recoverable_via=f'screen="{screen}", section="{sec["name"]}"',
        ))
    if sec["component_refs"]:
        lines.append("\n## Componentes")
        for comp in sec["component_refs"]:
            lines.append(f"- **{comp}**")
    if sec["texts"]:
        lines.append("\n## Textos")
        for t in sec["texts"][:8]:
            lines.append(f'- "{t}"')
        notice = truncation_notice(
            len(sec["texts"]), 8,
            recoverable_via=f'screen="{screen}", section="{sec["name"]}"', aspect="texts",
        )
        if notice:
            lines.append(notice)
    if sec["source_code"]:
        lines.extend(source_block_lines(
            sec["source_code"], sec["source_lang"], 3000, recoverable_via=None, heading="\n## Fonte",
        ))
    return "\n".join(lines)
