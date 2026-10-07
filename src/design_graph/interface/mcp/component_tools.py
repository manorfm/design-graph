"""Component tools: one component's spec, subtree, props, children, interactions and data."""

from __future__ import annotations

import logging

from design_graph.model.graph.reader import GraphReader
from design_graph.interface.mcp.full_tools import get_full_source
from design_graph.interface.mcp.markdown import (
    action_lines,
    state_lines,
    mode_tag,
    component_lines,
    dedupe_styles_by_property,
    props_table_lines,
    referenced_data_lines,
)
from design_graph.interface.mcp.notices import (
    StyleExtractionGap,
    source_block_lines,
    truncation_notice,
)

logger = logging.getLogger(__name__)


# Default page size for list_components — the only listing tool that had no
# cap at all (search/get_screen_full/get_component_spec already truncate).
DEFAULT_LIST_COMPONENTS_LIMIT = 100


def _not_found(name: str) -> str:
    return f"Componente '{name}' não encontrado. Use search('{name}') para explorar."


def _screen_instead(reader: GraphReader, name: str) -> str | None:
    """
    The answer for a component tool asked about a screen: the screen's own
    source, the components it uses directly and where to get the whole page.
    None when `name` is not a screen.
    """
    entity = reader.resolve_named_entity(name).entity
    if entity is None or entity.kind != "screen":
        return None
    screen = reader.get_screen(entity.name) or {}
    components = ", ".join(c["c.name"] for c in screen.get("components", [])) or "nenhum"
    return "\n".join([
        f"# '{entity.name}' é uma tela, não um componente",
        f"**Componentes diretos**: {components}",
        f"> Para montar a tela: assemble_page('{entity.name}'); para inspecioná-la inteira: "
        f"get_screen(name=\"{entity.name}\", detail=\"full\").\n",
        get_full_source(reader, entity.name),
    ])


def get_component(reader: GraphReader, name: str, depth: object = 0) -> str:
    """
    One component, whole: its spec (hierarchy, styles by state, tokens,
    texts, interactions, props, referenced data, source) — and with depth 1
    to 3 the components it nests, that many levels down. A screen's name is
    answered as that screen.
    """
    try:
        levels = int(depth)
    except (TypeError, ValueError):
        levels = -1
    if not 0 <= levels <= 3:
        return f"depth inválido: {depth!r}. Use 0 (só o componente) a 3 (com os aninhados até 3 níveis)."
    return get_component_spec(reader, name) if levels == 0 else get_component_full(reader, name, levels)


def get_component_spec(reader: GraphReader, name: str) -> str:
    spec = reader.get_component_spec(name)
    if not spec:
        class_styles = reader.find_styles_by_class(name)
        if class_styles:
            return _render_shared_css_class_spec(reader, name, class_styles)
        return _screen_instead(reader, name) or _not_found(name)

    cname = spec["c.name"]
    lines = [
        f"# Spec: {cname}",
        f"**Tipo**: {spec['c.comp_type']} | **Ocorrências**: {spec['c.occurrence']}",
    ]
    if spec.get("screens_using"):
        lines.append(f"**Telas**: {', '.join(spec['screens_using'])}")
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
            lines.append(f"| {t.get('t.label')}{mode_tag(t.get('t.mode'))} | {t.get('t.value')} | {t.get('t.category')} |")
    if spec.get("texts"):
        lines.append("\n## Textos")
        for t in spec["texts"][:8]:
            lines.append(f'- "{t.get("t.content")}" ({t.get("t.text_type")})')
        notice = truncation_notice(len(spec["texts"]), 8, recoverable_via=cname, aspect="texts")
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
    if spec.get("states"):
        lines.append("\n## Estado")
        lines.extend(state_lines(spec["states"]))
    if spec.get("actions"):
        lines.append("\n## Ações")
        lines.extend(action_lines(spec["actions"]))
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


def get_component_full(reader: GraphReader, name: str, depth: int = 3) -> str:
    """
    Render the root component plus every descendant (via CONTAINS, up to
    `depth` levels) as Markdown — one call to reconstruct a complex
    component instead of asking for each nested one.
    """
    full = reader.get_component_full(name, depth)
    if not full:
        return _screen_instead(reader, name) or _not_found(name)

    root_name = full["root"]
    lines = [
        f"# Árvore de componente: {root_name}",
        f"**Componentes na árvore**: {len(full['components'])}\n",
    ]
    for comp in full["components"]:
        marker = " (raiz)" if comp["name"] == root_name else ""
        lines.extend(component_lines(comp, heading=f"## {comp['name']}{marker}"))

    logger.debug("tools: get_component_full(%s) — %d components", root_name, len(full["components"]))
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
