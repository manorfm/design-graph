"""Component tools: one component's spec, subtree, props, children, interactions and data."""

from __future__ import annotations

import logging

from design_graph.model.entities import StyleState
from design_graph.model.graph.reader import GraphReader
from design_graph.interface.mcp.markdown import (
    dedupe_styles_by_property,
    named_entity_resolution_error,
    props_table_lines,
    referenced_data_lines,
    render_referenced_data_value,
)
from design_graph.interface.mcp.notices import (
    StyleExtractionGap,
    source_block_lines,
    truncated_fields_notice,
    truncation_notice,
)

logger = logging.getLogger(__name__)


# Default page size for list_components — the only listing tool that had no
# cap at all (search/get_screen_full/get_component_spec already truncate).
DEFAULT_LIST_COMPONENTS_LIMIT = 100


def get_component(reader: GraphReader, name: str) -> str:
    comp = reader.get_component(name)
    if not comp:
        return f"Componente '{name}' não encontrado. Use search('{name}') para explorar."

    cname = comp.get("c.name", name)
    lines = [
        f"# Componente: {cname}",
        f"Tipo: **{comp.get('c.comp_type', '')}**  |  Ocorrências: {comp.get('c.occurrence', '')}",
        f"Usado em: {', '.join(comp.get('screens_using', [])) or 'não detectado'}",
    ]
    trunc_notice = truncated_fields_notice(comp.get("c.truncated_fields"), recoverable_via=cname)
    if trunc_notice:
        lines.append(trunc_notice)
    if comp.get("c.source_code"):
        lines += ["", *source_block_lines(
            comp["c.source_code"], comp["c.source_lang"], 4000, recoverable_via=cname, heading="## Fonte",
        )]
    if comp.get("styles"):
        lines.append("\n## Estilos")
        by_state: dict[str, list[str]] = {}
        for s in comp["styles"]:
            by_state.setdefault(s.get("s.state", "default"), []).append(
                f"`{s.get('s.property')}`: `{s.get('s.value')}`"
            )
        for state in StyleState:
            if state in by_state:
                lines.append(f"**{state}**: {' | '.join(by_state[state][:6])}")
    else:
        notice = StyleExtractionGap(bool(comp.get("c.declares_inline_styles"))).notice()
        if notice:
            lines.append(f"\n{notice}")
    if comp.get("tokens"):
        lines.append("\n## Tokens de design")
        for t in comp["tokens"]:
            lines.append(f"- **{t.get('t.label')}** = `{t.get('t.value')}` ({t.get('t.category')})")
    if comp.get("children"):
        lines.append(f"\n## Componentes filhos\n{', '.join(comp['children'])}")
    if comp.get("referenced_data"):
        lines.append("\n## Dados referenciados")
        lines.extend(referenced_data_lines(comp["referenced_data"], recoverable_via=cname))
    return "\n".join(lines)


def get_component_spec(reader: GraphReader, name: str) -> str:
    spec = reader.get_component_spec(name)
    if not spec:
        class_styles = reader.find_styles_by_class(name)
        if class_styles:
            return _render_shared_css_class_spec(reader, name, class_styles)
        return f"Componente '{name}' não encontrado. Use search('{name}') para explorar."

    cname = spec["c.name"]
    lines = [
        f"# Spec: {cname}",
        f"**Tipo**: {spec['c.comp_type']} | **Ocorrências**: {spec['c.occurrence']}",
    ]
    if spec.get("screens_using"):
        lines.append(f"**Telas**: {', '.join(spec['screens_using'])}")
    trunc_notice = truncated_fields_notice(spec.get("c.truncated_fields"), recoverable_via=cname)
    if trunc_notice:
        lines.append(trunc_notice)
    if spec.get("parents") or spec.get("children"):
        lines.append("\n## Hierarquia")
        if spec["parents"]:
            lines.append(f"- Pais: {', '.join(spec['parents'])}")
        if spec["children"]:
            lines.append(f"- Filhos: {', '.join(spec['children'])}")
    if spec.get("styles_by_state"):
        for state, raw_styles in sorted(spec["styles_by_state"].items()):
            styles = dedupe_styles_by_property(raw_styles)
            lines.append(f"\n## Estilos — {state}")
            lines.append("| Propriedade | Valor |")
            lines.append("|---|---|")
            for s in styles[:12]:
                lines.append(f"| {s['property']} | {s['value']} |")
            notice = truncation_notice(len(styles), 12, recoverable_via=cname)
            if notice:
                lines.append(notice)
    else:
        notice = StyleExtractionGap(bool(spec.get("c.declares_inline_styles"))).notice()
        if notice:
            lines.append(f"\n{notice}")
    if spec.get("responsive_styles_by_media"):
        lines.append("\n## Estilos responsivos")
        lines.append(
            "Valores abaixo só se aplicam sob a condição `@media` indicada — "
            "não confundir com o valor default acima."
        )
        for media, raw_styles in spec["responsive_styles_by_media"].items():
            styles = dedupe_styles_by_property(raw_styles)
            lines.append(f"\n**`@media {media}`**")
            lines.append("| Propriedade | Valor |")
            lines.append("|---|---|")
            for s in styles[:12]:
                lines.append(f"| {s['property']} | {s['value']} |")
            notice = truncation_notice(len(styles), 12, recoverable_via=cname)
            if notice:
                lines.append(notice)
    if spec.get("tokens"):
        lines.append("\n## Tokens")
        lines.append("| Label | Valor | Categoria |")
        lines.append("|---|---|---|")
        for t in spec["tokens"]:
            lines.append(f"| {t.get('t.label')} | {t.get('t.value')} | {t.get('t.category')} |")
    if spec.get("texts"):
        lines.append("\n## Textos")
        for t in spec["texts"][:8]:
            lines.append(f'- "{t.get("t.content")}" ({t.get("t.text_type")})')
        notice = truncation_notice(len(spec["texts"]), 8, recoverable_via=cname, tool="get_full_texts")
        if notice:
            lines.append(notice)
    if spec.get("interactions"):
        lines.append("\n## Interações")
        for i in spec["interactions"]:
            lines.append(
                f"- {i.get('i.trigger')}: {i.get('i.css_prop')} "
                f"`{i.get('i.from_val')}` → `{i.get('i.to_val')}` ({i.get('i.transition')})"
            )
    if spec.get("props"):
        lines.append("\n## Props")
        lines.extend(props_table_lines(spec["props"]))
    if spec.get("referenced_data"):
        lines.append("\n## Dados referenciados")
        lines.append(
            "> Constantes do módulo (fora de qualquer função) que o corpo deste "
            "componente referencia pelo nome — ex.: um mapa nome-do-ícone → path "
            "SVG indexado como `ICONS[name]`. Use os mesmos valores ao reimplementar, "
            "em vez de outro ícone/dado equivalente."
        )
        lines.extend(referenced_data_lines(spec["referenced_data"], recoverable_via=cname))
    if spec.get("c.source_code"):
        lines.extend(source_block_lines(
            spec["c.source_code"], spec["c.source_lang"], 3000, recoverable_via=cname, heading="\n## Fonte",
        ))
    logger.debug("tools: get_component_spec(%s) — rendered", cname)
    return "\n".join(lines)


def _render_shared_css_class_spec(
    reader: GraphReader, class_name: str, styles: list[dict],
) -> str:
    """
    Render a CSS class that was never factored into a named React
    component (e.g. `.page-title`, `.chip`, `.audit-dot` — shared by
    several screens' own inline markup) as a spec, clearly labeled as a
    class rather than a component so it's never mistaken for one (see
    docs/changes/C36 P3).
    """
    owners = reader.find_class_owners(class_name)
    lines = [
        f"# Spec: .{class_name}",
        "**Tipo**: classe CSS (não é um componente nomeado)",
    ]
    used_in = [*owners["components"], *(f'{o["screen"]} / {o["section"]}' for o in owners["sections"])]
    if used_in:
        lines.append(f"**Usado em**: {', '.join(used_in)}")
    lines.append("\n## Estilos")
    lines.append("| Propriedade | Valor |")
    lines.append("|---|---|")
    for s in styles:
        lines.append(f"| {s['property']} | {s['value']} |")
    return "\n".join(lines)


def get_component_full(reader: GraphReader, name: str) -> str:
    """
    Render the root component plus every descendant (via CONTAINS, up
    to 3 levels) as Markdown — one call to reconstruct a complex
    component instead of cascading get_component_children per level.
    """
    full = reader.get_component_full(name)
    if not full:
        return f"Componente '{name}' não encontrado. Use search('{name}') para explorar."

    root_name = full["root"]
    lines = [
        f"# Árvore de componente: {root_name}",
        f"**Componentes na árvore**: {len(full['components'])}\n",
    ]
    for comp in full["components"]:
        cname = comp["name"]
        marker = " (raiz)" if cname == root_name else ""
        lines.append(f"## {cname}{marker}")
        lines.append(f"**Tipo**: {comp['comp_type']} | **Ocorrências**: {comp['occurrence']}")
        trunc_notice = truncated_fields_notice(comp.get("truncated_fields"), recoverable_via=cname)
        if trunc_notice:
            lines.append(trunc_notice)
        if comp["children"]:
            lines.append(f"**Filhos**: {', '.join(comp['children'])}")

        if comp["props"]:
            lines.append("\n#### Props")
            lines.extend(props_table_lines(comp["props"]))

        any_styles = False
        for state, raw_styles in sorted(comp["styles_by_state"].items()):
            styles = dedupe_styles_by_property(raw_styles)
            if styles:
                any_styles = True
                lines.append(f"\n#### Estilos — {state}")
                lines.append("| Propriedade | Valor |")
                lines.append("|---|---|")
                for s in styles[:12]:
                    lines.append(f"| {s['property']} | {s['value']} |")
                notice = truncation_notice(len(styles), 12, recoverable_via=cname)
                if notice:
                    lines.append(notice)
        if not any_styles:
            notice = StyleExtractionGap(comp["declares_inline_styles"]).notice()
            if notice:
                lines.append(f"\n{notice}")

        if comp["tokens"]:
            lines.append("\n#### Tokens")
            for t in comp["tokens"]:
                lines.append(f"- **{t['label']}** = `{t['value']}` ({t['category']})")

        if comp["interactions"]:
            lines.append("\n#### Interações")
            for i in comp["interactions"]:
                lines.append(
                    f"- **{i['trigger']}**: `{i['css_prop']}` "
                    f"`{i['from_val']}` → `{i['to_val']}` ({i['transition']})"
                )

        if comp["texts"]:
            lines.append("\n#### Textos")
            for t in comp["texts"][:8]:
                lines.append(f'- "{t["content"]}" ({t["text_type"]})')
            notice = truncation_notice(len(comp["texts"]), 8, recoverable_via=cname, tool="get_full_texts")
            if notice:
                lines.append(notice)

        if comp.get("referenced_data"):
            lines.append("\n#### Dados referenciados")
            lines.extend(referenced_data_lines(comp["referenced_data"], recoverable_via=cname))

        if comp["source_code"]:
            lines.append("")
            lines.extend(source_block_lines(comp["source_code"], comp["source_lang"], 2500, recoverable_via=cname))
        lines.append("")

    logger.debug("tools: get_component_full(%s) — %d components", root_name, len(full["components"]))
    return "\n".join(lines)


def get_component_props(reader: GraphReader, name: str) -> str:
    """Return declared props for a component as a Markdown table."""
    props = reader.get_component_props(name)
    if not props:
        return (
            f"No declared props found for '{name}'. "
            "The component may use positional props, TypeScript interfaces, or have no props."
        )
    lines = [f"# Props: {name}\n", *props_table_lines(props)]
    logger.debug("tools: get_component_props(%s) — %d props", name, len(props))
    return "\n".join(lines)


def get_component_children(reader: GraphReader, name: str) -> str:
    children = reader.get_component_children(name)
    if not children:
        if not reader.component_exists(name):
            return f"'{name}' não encontrado. Use search() para localizar."
        return f"'{name}' é um componente folha — não possui filhos detectados."
    lines = [f"# Filhos de: {name}\n"]
    for child in children:
        lines.append(f"- `{child}`")
    return "\n".join(lines)


def get_component_interactions(reader: GraphReader, name: str) -> str:
    interactions = reader.get_interactions(name)
    if not interactions:
        return f"Nenhuma interação detectada para '{name}'."
    lines = [f"# Interações: {name}\n"]
    for i in interactions:
        lines.append(f"**{i.get('i.trigger', '').upper()}**")
        lines.append(f"  Propriedade: `{i.get('i.css_prop')}`")
        if i.get("i.from_val"):
            lines.append(f"  De: `{i['i.from_val']}`")
        lines.append(f"  Para: `{i.get('i.to_val')}`")
        if i.get("i.transition"):
            lines.append(f"  Transition: `{i['i.transition']}`")
        lines.append("")
    return "\n".join(lines)


def get_component_data(reader: GraphReader, name: str) -> str:
    """
    Uncapped referenced-module-data — the get_full_styles/get_full_texts
    equivalent for a component's referenced_data (see
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


def list_components(reader: GraphReader, comp_type: str | None, limit: int | None = None) -> str:
    comps = reader.list_components(comp_type)
    if not comps:
        if comp_type:
            return f"Nenhum componente encontrado para o tipo '{comp_type}'."
        return "Nenhum componente encontrado."

    # Unlike every other listing tool (search, get_screen_full,
    # get_component_spec), this had no cap at all — a prototype with
    # hundreds of components returned every row in one response,
    # against the product's own point of reducing tokens in the
    # agent's context. Already sorted by occurrence DESC (reader.list_components),
    # so the shown slice is the most-used components, not an arbitrary cut.
    effective_limit = limit if limit and limit > 0 else DEFAULT_LIST_COMPONENTS_LIMIT
    shown = comps[:effective_limit]

    header = f"## Componentes — tipo: {comp_type}" if comp_type else "## Componentes"
    lines = [header, f"({len(comps)} encontrados)\n",
             "| Nome | Tipo | Ocorrências |",
             "|------|------|-------------|"]
    for c in shown:
        lines.append(f"| {c['c.name']} | {c['c.comp_type']} | {c['c.occurrence']} |")
    notice = truncation_notice(len(comps), len(shown))
    if notice:
        lines.append(notice + " (passe limit= para ver mais, ou comp_type= para filtrar)")
    logger.debug("tools: list_components(type=%s) → %d/%d rows shown", comp_type, len(shown), len(comps))
    return "\n".join(lines)
