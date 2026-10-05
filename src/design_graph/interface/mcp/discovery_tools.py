"""Discovery tools: tokens, token usage, search across prototypes and impact analysis."""

from __future__ import annotations

from design_graph.model.graph.reader import GraphReader
from design_graph.interface.mcp.markdown import mode_tag
from design_graph.interface.mcp.search import SearchResult, search


def _hierarchy_tag(item: SearchResult) -> str:
    """
    Trailing " (pais: X; telas: Y)" for a Component search hit that has
    graph context — same "Pais"/"Telas" vocabulary get_component_spec
    already uses (see `get_component_spec` below), so a search result reads
    consistently with a full spec instead of introducing new terms. Empty
    for every non-Component result and for a Component with neither.
    """
    if item.type != "Component":
        return ""
    bits = []
    if item.parents:
        bits.append(f"pais: {', '.join(item.parents)}")
    if item.screens_using:
        bits.append(f"telas: {', '.join(item.screens_using)}")
    return f" _({'; '.join(bits)})_" if bits else ""


def get_tokens(
    reader: GraphReader, category: str | None, screen: str | None = None, mode: str | None = None,
) -> str:
    rows = reader.get_tokens(category, screen, mode)
    if not rows:
        return (
            f"Nenhum token encontrado para a tela '{screen}'." if screen
            else "Nenhum token encontrado."
        )
    lines = [f"# Design Tokens — tela {screen}\n" if screen else "# Design Tokens\n"]
    by_cat: dict[str, list] = {}
    for r in rows:
        by_cat.setdefault(r.get("t.category", "?"), []).append(r)
    for cat, tokens in sorted(by_cat.items()):
        lines.append(f"## {cat}")
        for t in tokens:
            lines.append(f"- **{t.get('t.label')}**{mode_tag(t.get('t.mode'))}: `{t.get('t.value')}` ({t.get('t.usage')} usos)")
        lines.append("")
    return "\n".join(lines)


# What an agent does with each kind, in the order it needs to know it.
_RESOURCE_GROUPS = (
    ("library", "Bibliotecas (declarar no projeto, não copiar)"),
    ("font", "Fontes"),
    ("image", "Imagens"),
    ("runtime", "Não reproduzir (infraestrutura do protótipo)"),
    ("module", "Módulos do protótipo"),
)


def get_resources(reader: GraphReader, kind: str | None, screen: str | None = None) -> str:
    rows = reader.get_resources(kind, screen)
    if not rows:
        return f"Nenhum recurso encontrado{f' para a tela {screen!r}' if screen else ''}."
    lines = [f"# Recursos — tela {screen}\n" if screen else "# Recursos\n"]
    for group, title in _RESOURCE_GROUPS:
        members = [r for r in rows if r["kind"] == group]
        if members:
            lines.append(f"## {title}")
            lines.extend(_resource_line(r) for r in members)
            lines.append("")
    return "\n".join(lines)


def _resource_line(row: dict) -> str:
    origin = f"{row['origin']} ({row['certainty']})" if row["certainty"] == "inferida" else row["origin"]
    parts = [f"- **{row['name']}**" + (f" {row['version']}" if row["version"] else "")]
    parts += [part for part in (row["detail"], origin) if part]
    return " · ".join(parts)


def find_token_usage(reader: GraphReader, value: str) -> str:
    usages = reader.find_token_usage(value)
    if not usages:
        return f"Token '{value}' não encontrado."
    lines = [f"# Uso do token: `{value}`\n"]
    for u in usages:
        lines.append(f"## {u.get('t.label')} = `{u.get('t.value')}` ({u.get('t.category')})")
        if u.get("components"):
            comps = ", ".join(c.get("c.name", "") for c in u["components"])
            lines.append(f"Componentes: {comps}")
        if u.get("screens"):
            lines.append(f"Telas: {', '.join(u['screens'])}")
        lines.append("")
    return "\n".join(lines)


def tool_search(readers: list[tuple[str, GraphReader]], query: str) -> str:
    results = search(readers, query)
    if not results:
        return f"Nenhum resultado para '{query}'."
    shown = results[:30]
    lines = [f"# Resultados para: '{query}'\n"]
    if all(r.word_coverage < 1.0 for r in shown):
        lines.append(
            "> Nenhum resultado cobre todas as palavras da busca — os itens "
            "abaixo são correspondências **parciais** (compartilham só parte "
            "dos termos), não confirmam que a frase completa existe no "
            "protótipo.\n"
        )
    by_type: dict[str, list] = {}
    for r in shown:
        by_type.setdefault(r.type, []).append(r)
    for t, items in sorted(by_type.items()):
        lines.append(f"## {t}")
        for item in items:
            doc_tag = f" `[{item.doc}]`" if len(readers) > 1 else ""
            detail  = f" — {item.detail}" if item.detail else ""
            partial_tag = " *(parcial)*" if item.word_coverage < 1.0 else ""
            lines.append(f"- **{item.name}**{doc_tag}{detail}{partial_tag}{_hierarchy_tag(item)}")
        lines.append("")
    return "\n".join(lines)


def impact(reader: GraphReader, name: str) -> str:
    result = reader.get_impact(name)
    if not result.get("found"):
        return f"'{name}' não encontrado. Use search() para localizar."
    lines = [f"# Análise de impacto: {name}\n"]
    if "type" in result:
        lines.append(f"Tipo: **{result['type']}**")
        lines.append(f"\n## Telas afetadas ({len(result.get('screens', []))})")
        for s in result.get("screens", []):
            lines.append(f"- {s}")
    elif "label" in result:
        lines.append(f"Token: **{result['label']}** = `{result['value']}`")
        lines.append(f"\n## Componentes que usam este token ({len(result.get('components', []))})")
        for c in result.get("components", []):
            lines.append(f"- {c}")
    return "\n".join(lines)
