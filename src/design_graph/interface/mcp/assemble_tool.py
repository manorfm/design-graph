"""
assemble_page — "build this screen" in one call.

Sections in a fixed order (the response contract): 1 header, 2 skeleton (the
screen's own source), 3 each component it renders, once — minus the ones the
agent says it already has (`known`), 4 the data they repeat, 6 the tokens it
uses by mode, 7 what to install, 8 what was left out and where it is. Section
5 (behaviour) is not captured yet. A long answer comes in parts, cut between
blocks, never inside one without saying so.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from design_graph.interface.mcp.discovery_tools import resource_lines
from design_graph.interface.mcp.full_tools import source_parts
from design_graph.interface.mcp.markdown import props_table_lines, screen_relation_lines
from design_graph.model.graph.reader import GraphReader

ASSEMBLY_PART_CHARS = 20_000


@dataclass(frozen=True)
class _Block:
    title: str   # what the block holds, for the summary of parts
    text: str


def assemble_page(reader: GraphReader, name: str, known: object = None, part: object = 1) -> str:
    assembly = reader.get_screen_assembly(name)
    if not assembly:
        return f"Tela '{name}' não encontrada. Use list_screens() para ver as telas do protótipo."
    known_names = _names(known)
    parts = _pack(_blocks(assembly, known_names))
    number = _part_number(part, len(parts))
    if number is None:
        return f"Parte inválida: {part!r}. A montagem de '{assembly['name']}' tem as partes 1 a {len(parts)}."

    heading = f"# Montar: {assembly['name']}"
    lines = [heading if len(parts) == 1 else f"{heading} — parte {number}/{len(parts)}", ""]
    if len(parts) > 1 and number == 1:
        lines += ["### Partes", *(f"- Parte {n}: {', '.join(b.title for b in blocks)}" for n, blocks in enumerate(parts, 1)), ""]
    lines += [block.text for block in parts[number - 1]]
    if number < len(parts):
        same_known = " — com o mesmo known" if known_names else ""
        lines.append(f"> Continua: assemble_page('{assembly['name']}', part={number + 1}){same_known}")
    return "\n".join(lines)


# ── Blocks ────────────────────────────────────────────────────────────────────

def _blocks(assembly: dict, known: set[str]) -> list[_Block]:
    components = [c for c in assembly["components"] if c["name"] not in known]
    omitted = [c["name"] for c in assembly["components"] if c["name"] in known]
    lang = assembly["source_lang"]
    return [
        _Block("1. Cabeçalho", "\n".join(["## 1. Cabeçalho", *_header_lines(assembly), ""])),
        *_code_blocks("2. Esqueleto", "## 2. Esqueleto", assembly["skeleton"], lang),
        _Block("3. Componentes", "## 3. Componentes\n" + ("" if components else "Nenhum além dos que você já tem.\n")),
        *(block for component in components for block in _component_blocks(component)),
        _Block("4. Dados", "\n".join(["## 4. Dados", *_data_lines(components), ""])),
        _Block("6. Tokens", "\n".join(["## 6. Tokens usados, por modo", *_token_lines(assembly["tokens"]), ""])),
        _Block("7. Dependências", "\n".join(["## 7. Dependências", *(resource_lines(assembly["resources"], heading="###")
                                                                    or ["Nenhuma registrada."]), ""])),
        _Block("8. Completude", "\n".join(["## 8. Completude", *_completeness_lines(assembly["name"], omitted), ""])),
    ]


def _header_lines(assembly: dict) -> list[str]:
    modes = sorted({t["t.mode"] for t in assembly["tokens"] if t.get("t.mode")})
    lines = [*screen_relation_lines(assembly["relations"]), f"**Linguagem**: {assembly['source_lang'] or 'n/d'}"]
    if modes:
        lines.append(f"**Modos**: {', '.join(modes)}")
    names = [c["name"] for c in assembly["components"]]
    lines.append(f"**Componentes**: {', '.join(names) if names else 'nenhum'}")
    return lines


def _component_blocks(component: dict) -> list[_Block]:
    heading = f"### {component['name']}"
    if not component["defined"]:
        return [_Block(component["name"], f"{heading}\nReferenciado, sem definição no protótipo (externo ou de biblioteca).\n")]
    intro = [heading, f"**Tipo**: {component['comp_type']}"]
    if component["props"]:
        intro += ["", *props_table_lines(component["props"])]
    blocks = _code_blocks(component["name"], "\n".join(intro), component["source_code"], component["source_lang"])
    return blocks


def _code_blocks(title: str, intro: str, code: str, lang: str) -> list[_Block]:
    """A block of code, split into several when it is longer than a part — each piece saying it continues."""
    pieces = source_parts(code, ASSEMBLY_PART_CHARS - len(intro) - 200)
    blocks = []
    for n, (text, mid_line) in enumerate(pieces, 1):
        label = intro if n == 1 else f"{intro.splitlines()[0]} (continuação {n}/{len(pieces)})"
        note = "\n> Esta parte termina no meio de uma linha: a próxima continua a mesma linha." if mid_line else ""
        blocks.append(_Block(title if len(pieces) == 1 else f"{title} ({n}/{len(pieces)})",
                             f"{label}\n```{lang}\n{text}\n```{note}\n"))
    return blocks


def _data_lines(components: list[dict]) -> list[str]:
    lines = [
        f"- **{c['name']}** · `{key}`: `{json.dumps(value, ensure_ascii=False)}`"
        for c in components for key, value in c["referenced_data"].items()
    ]
    return lines or ["Nenhum dado repetido."]


def _token_lines(rows: list[dict]) -> list[str]:
    by_label: dict[str, list[tuple[str, str]]] = {}
    for row in rows:
        by_label.setdefault(row["t.label"], []).append((row.get("t.mode") or "", row["t.value"]))
    lines = []
    for label, values in by_label.items():
        if len(values) == 1 and not values[0][0]:
            lines.append(f"- **{label}**: `{values[0][1]}`")
        else:
            lines.append(f"- **{label}**: " + " · ".join(f"{mode} `{value}`" if mode else f"`{value}`" for mode, value in values))
    return lines or ["Nenhum token ligado aos componentes desta tela."]


def _completeness_lines(screen: str, omitted: list[str]) -> list[str]:
    lines = ["Tudo o que a tela usa está acima — nada foi cortado."]
    if omitted:
        lines.append(f"Omitidos (você já tem): {', '.join(omitted)}")
    lines += [
        f"Fonte original da tela, como escrito: get_full_source('{screen}')",
        "Comportamento (o que cada ação faz) ainda não é capturado.",
    ]
    return lines


# ── Parts ─────────────────────────────────────────────────────────────────────

def _pack(blocks: list[_Block]) -> list[list[_Block]]:
    """Blocks packed in order into parts of at most ASSEMBLY_PART_CHARS — a part breaks only between blocks."""
    parts: list[list[_Block]] = [[]]
    size = 0
    for block in blocks:
        if parts[-1] and size + len(block.text) > ASSEMBLY_PART_CHARS:
            parts.append([])
            size = 0
        parts[-1].append(block)
        size += len(block.text)
    return parts


def _names(known: object) -> set[str]:
    """`known` as component names: a list of them or one comma-separated string; anything else is ignored."""
    if isinstance(known, str):
        return {name.strip() for name in known.split(",") if name.strip()}
    if isinstance(known, list):
        return {name.strip() for name in known if isinstance(name, str) and name.strip()}
    return set()


def _part_number(part: object, total: int) -> int | None:
    try:
        number = int(part)
    except (TypeError, ValueError):
        return None
    return number if 1 <= number <= total else None
