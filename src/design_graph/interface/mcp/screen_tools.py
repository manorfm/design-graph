"""Screen tools: listing screens and reconstructing one screen, its layout or a section."""

from __future__ import annotations

import json
import logging

from design_graph.model.entities import StyleState
from design_graph.model.graph.reader import GraphReader
from design_graph.interface.mcp.markdown import (
    dedupe_styles_by_property,
    props_table_lines,
    referenced_data_lines,
    section_style_group_lines,
)
from design_graph.interface.mcp.notices import (
    CappedJsx,
    ScreenStructureGap,
    StyleExtractionGap,
    truncated_fields_notice,
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
            lines.append(f"**{s['name']}** ({s['component_count']} componentes)")
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
      ## Sections — each with styles, component refs, texts and JSX
      ## Components — each with styles-by-state, tokens, interactions, props, children, JSX

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
        "",
    ]

    if not spec["sections"] and not spec["components"]:
        gap_notice = ScreenStructureGap(spec.get("source_code", "")).notice(
            recoverable_via=spec["name"]
        )
        if gap_notice:
            lines.append(gap_notice)
            lines.append("")

    # ── Sections ──────────────────────────────────────────────────────────
    if spec["sections"]:
        lines.append("## Sections\n")
        for sec in spec["sections"]:
            lines.append(f"### {sec['name']}")
            lines.append(f"*Detection*: {sec['detection_method']}")
            if sec["component_refs"]:
                lines.append(f"**Components**: {', '.join(sec['component_refs'])}")
            if sec["styles_by_element"]:
                lines.append("**Styles**:")
                lines.extend(section_style_group_lines(
                    sec["styles_by_element"], recoverable_via=f'screen="{spec["name"]}", section="{sec["name"]}"',
                ))
            if sec["texts"]:
                for t in sec["texts"][:6]:
                    lines.append(f'- "{t}"')
                notice = truncation_notice(
                    len(sec["texts"]), 6,
                    recoverable_via=f'screen="{spec["name"]}", section="{sec["name"]}"', tool="get_full_texts",
                )
                if notice:
                    lines.append(notice)
            if sec["source_code"]:
                jsx = CappedJsx(sec["source_code"], 2000)
                lines.append("\n```jsx")
                lines.append(jsx)
                lines.append("```")
                notice = jsx.notice(recoverable_via=None)  # sections aren't Component nodes
                if notice:
                    lines.append(notice)
            lines.append("")

    # ── Components ────────────────────────────────────────────────────────
    if spec["components"]:
        lines.append("---\n## Components\n")
        for comp in spec["components"]:
            cname = comp["name"]
            lines.append(f"### {cname}")
            lines.append(f"**Type**: {comp['comp_type']} | **Occurrences**: {comp['occurrence']}")
            trunc_notice = truncated_fields_notice(comp.get("truncated_fields"), recoverable_via=cname)
            if trunc_notice:
                lines.append(trunc_notice)
            if comp["children"]:
                lines.append(f"**Children**: {', '.join(comp['children'])}")

            if comp["props"]:
                lines.append("\n#### Props")
                lines.extend(props_table_lines(comp["props"]))

            any_styles = False
            for state in StyleState:
                state_styles = dedupe_styles_by_property(comp["styles_by_state"].get(state, []))
                if state_styles:
                    any_styles = True
                    lines.append(f"\n#### Styles — {state}")
                    lines.append("| Property | Value |")
                    lines.append("|---|---|")
                    for s in state_styles[:12]:
                        lines.append(f"| {s['property']} | {s['value']} |")
                    notice = truncation_notice(len(state_styles), 12, recoverable_via=cname)
                    if notice:
                        lines.append(notice)
            if not any_styles:
                notice = StyleExtractionGap(comp["declares_inline_styles"]).notice()
                if notice:
                    lines.append(f"\n{notice}")

            if comp["tokens"]:
                lines.append("\n#### Tokens")
                lines.append("| Label | Value | Category |")
                lines.append("|---|---|---|")
                for t in comp["tokens"]:
                    lines.append(f"| {t['label']} | {t['value']} | {t['category']} |")

            if comp["interactions"]:
                lines.append("\n#### Interactions")
                for i in comp["interactions"]:
                    lines.append(
                        f"- **{i['trigger']}**: `{i['css_prop']}` "
                        f"`{i['from_val']}` → `{i['to_val']}` ({i['transition']})"
                    )

            if comp["texts"]:
                lines.append("\n#### Texts")
                for t in comp["texts"][:8]:
                    lines.append(f'- "{t["content"]}" ({t["text_type"]})')
                notice = truncation_notice(len(comp["texts"]), 8, recoverable_via=cname, tool="get_full_texts")
                if notice:
                    lines.append(notice)

            if comp.get("referenced_data"):
                lines.append("\n#### Referenced data")
                lines.extend(referenced_data_lines(comp["referenced_data"], recoverable_via=cname))

            if comp["source_code"]:
                jsx = CappedJsx(comp["source_code"], 2500)
                lines.append("\n```jsx")
                lines.append(jsx)
                lines.append("```")
                notice = jsx.notice(recoverable_via=cname)
                if notice:
                    lines.append(notice)
            lines.append("")

    logger.debug("tools: get_screen_full(%s) — rendered", spec["name"])
    return "\n".join(lines)


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
            recoverable_via=f'screen="{screen}", section="{sec["name"]}"', tool="get_full_texts",
        )
        if notice:
            lines.append(notice)
    if sec["source_code"]:
        jsx = CappedJsx(sec["source_code"], 3000)
        lines.append("\n## JSX\n```jsx")
        lines.append(jsx)
        lines.append("```")
        notice = jsx.notice(recoverable_via=None)  # sections aren't Component nodes
        if notice:
            lines.append(notice)
    return "\n".join(lines)
