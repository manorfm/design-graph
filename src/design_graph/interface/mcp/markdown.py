"""Markdown fragments shared by several tools."""

from __future__ import annotations

import json

from design_graph.model.entities import PropDefault
from design_graph.model.graph.reader import NamedEntityResolution
from design_graph.interface.mcp.notices import truncation_notice


def named_entity_resolution_error(name: str, resolution: NamedEntityResolution) -> str | None:
    """Format failed or ambiguous cross-entity resolution once for all tools."""
    if resolution.is_ambiguous:
        candidates = ", ".join(
            f"{candidate.kind}='{candidate.name}'" for candidate in resolution.candidates
        )
        return f"Nome '{name}' é ambíguo: {candidates}. Informe o nome exato da entidade desejada."
    if resolution.entity is None:
        return f"Nome '{name}' não encontrado. Use search('{name}') para explorar."
    return None


def props_table_lines(props: list[dict]) -> list[str]:
    """
    A one-line honesty note plus a Prop/Default Markdown table.

    No "Required" column: prototype sources don't declare which props are
    required, so a missing default is not proof a prop is required — only PropDefault's
    verifiable fact (whether a default exists, and what it is) is shown.
    """
    lines = [
        "> A missing default does not mean the prop is required — the prototype declares no such contract; check real usage before assuming.",
        "| Prop | Default |",
        "|---|---|",
    ]
    for p in props:
        prop_default = PropDefault(p["default_value"])
        lines.append(f"| `{p['prop_name']}` | {prop_default.as_table_cell()} |")
    return lines


def dedupe_styles_by_property(styles: list[dict]) -> list[dict]:
    """
    Collapse multiple rows for the same CSS property into one, joining
    distinct values with " | ".

    Conditional/mapped JSX (`color: i === 2 ? col : 'white'`) produces
    several style rows sharing one property name — truncating the raw list
    to a fixed cap can crowd out genuinely distinct properties before the
    reader ever sees them. Deduping by property first means the cap always
    bounds distinct properties, not raw rows.
    """
    values_by_property: dict[str, list[str]] = {}
    for entry in styles:
        values = values_by_property.setdefault(entry["property"], [])
        if entry["value"] not in values:
            values.append(entry["value"])
    return [
        {"property": prop, "value": " | ".join(values)}
        for prop, values in values_by_property.items()
    ]


_SECTION_STYLE_GROUP_CAP = 8


def section_style_group_lines(
    styles_by_element: dict[str, list[dict]], recoverable_via: str,
) -> list[str]:
    """
    Render a section's styles_by_element as Markdown, one sub-list per CSS
    selector — the section-level counterpart to get_component_spec's
    "Styles — {state}" grouping, grouped by selector instead of state (see
    docs/changes/C36: a flat property list gave no way to tell which of a
    section's several nested selectors a given value belonged to).
    """
    lines: list[str] = []
    for selector, raw_styles in sorted(styles_by_element.items()):
        styles = dedupe_styles_by_property(raw_styles)
        lines.append(f"- **{selector}**")
        for s in styles[:_SECTION_STYLE_GROUP_CAP]:
            lines.append(f"  - `{s['property']}`: `{s['value']}`")
        notice = truncation_notice(len(styles), _SECTION_STYLE_GROUP_CAP, recoverable_via=recoverable_via)
        if notice:
            lines.append(f"  {notice}")
    return lines


# Generous relative to styles(12)/texts(8): these tables are pure data (an
# icon-name -> SVG-path map, a role -> badge-metadata map), usually a dozen
# to a few dozen entries, and completeness is the whole point of capturing
# them at all — see docs/changes/C39.
_REFERENCED_DATA_ENTRY_CAP = 30


def render_referenced_data_value(value: object) -> str:
    """A referenced-constant's own value, rendered for one Markdown line —
    a bare string as-is (the common case: an SVG path, a CSS value), a
    dict/list as compact JSON (the ROLE_META-shaped nested case)."""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def referenced_data_lines(referenced_data: dict[str, object], recoverable_via: str) -> list[str]:
    """
    Render a component's referenced_data (module-level constants it
    references by name — see extraction/module_data_extractor.py) as
    Markdown, one sub-list per constant name, same truncation-notice
    convention every other capped table here already uses.
    """
    lines: list[str] = []
    for const_name, entries in sorted(referenced_data.items()):
        if not isinstance(entries, dict):
            # A referenced array (e.g. DETAIL_TABS-shaped) has no natural
            # "key" per entry — render positionally instead of forcing a
            # dict-only shape on every caller.
            items = list(enumerate(entries))
        else:
            items = list(entries.items())
        lines.append(f"- **{const_name}**")
        for key, value in items[:_REFERENCED_DATA_ENTRY_CAP]:
            lines.append(f"  - `{key}`: `{render_referenced_data_value(value)}`")
        notice = truncation_notice(
            len(items), _REFERENCED_DATA_ENTRY_CAP,
            recoverable_via=recoverable_via, tool="get_component_data",
        )
        if notice:
            lines.append(f"  {notice}")
    return lines
