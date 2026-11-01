"""Finite qualified-response packing over structured prose and opaque source.

No rendered Markdown is inspected. Every section is visited once; each nonempty
chunk consumes input. The page-count bound reserves the entire response envelope
before splitting, so neither a data-page annotation nor a contents index requires
a packing fixed point.
"""

from dataclasses import dataclass

from design_graph.interface.mcp.assemble_tool import ASSEMBLY_PART_CHARS
from design_graph.interface.mcp.full_tools import source_parts


@dataclass(frozen=True)
class Section:
    title: str
    text: str
    code: str | None = None
    lang: str = ""


def _text_chunks(text, capacity):
    return [text[start:start + capacity] for start in range(0, len(text), capacity)] or [""]


def _chunks(section, capacity):
    if section.code is None:
        return _text_chunks(section.text, capacity)
    whole = f"{section.text}\n```{section.lang}\n{section.code}\n```\n"
    if len(whole) <= capacity:
        return [whole]
    note = "\n> Esta parte termina no meio de uma linha: a próxima continua a mesma linha."
    # Reserve both the initial intro and the longest possible continuation
    # label. Decimal width is bounded by the number of source characters.
    digits = len(str(len(section.code) + 1))
    first_line = section.text.splitlines()[0] if section.text else ""
    continuation = f"{first_line} (continuação {'9' * digits}/{'9' * digits})"
    overhead = max(len(section.text), len(continuation)) + len(f"\n```{section.lang}\n\n```{note}\n")
    if capacity - overhead >= capacity // 2 and len(section.lang) <= 128:
        pieces = source_parts(section.code, capacity - overhead)
        blocks = []
        for n, (text, mid_line) in enumerate(pieces, 1):
            label = section.text if n == 1 else f"{first_line} (continuação {n}/{len(pieces)})"
            blocks.append(f"{label}\n```{section.lang}\n{text}\n```{note if mid_line else ''}\n")
        return blocks
    # Long intros are generated metadata, not source. Keep them in full, ahead
    # of the separately fenced source; never split an already rendered fence.
    intro = _text_chunks(section.text, capacity)
    lang = section.lang
    if len(lang) > 128:
        intro += _text_chunks(lang, capacity)
        lang = ""
    overhead = len(f"```{lang}\n\n```{note}\n")
    pieces = source_parts(section.code, capacity - overhead)
    return intro + [f"```{lang}\n{text}\n```{note if mid_line else ''}\n"
                    for text, mid_line in pieces]


def _plan(sections, heading, notice, tool):
    # Each emitted chunk contains at least one original character, except at
    # most two empty/fence-only chunks per section. Thus this is an upper bound
    # on page count, independent of packing and of the actual decimal widths.
    upper = 1 + sum(len(s.text) + len(s.code or "") + len(s.lang) + 2 for s in sections)
    digits = len(str(upper))
    largest = int("9" * digits)

    def prefix(n, total):
        text = f"{heading} — parte {n}/{total}\n{notice}\n"
        if n == 1:
            text += f"### Partes\n- Partes 1 a {total}: seções em ordem; continue com os mesmos argumentos.\n"
        return text

    def suffix(n, total):
        if n >= total:
            return ""
        return (f"\n> Continua: {tool}(part={n + 1}) — repeat identical "
                "db/snapshot/source_selections/name/known/aspect arguments.")

    reserve = max(len(prefix(1, largest)), len(prefix(largest, largest))) + len(suffix(1, largest)) + digits
    capacity = ASSEMBLY_PART_CHARS - reserve
    if capacity <= 256:
        raise ValueError("qualified response envelope exceeds page budget")
    pages = [[]]
    size = 0
    for section in sections:
        for chunk in _chunks(section, capacity):
            addition = len(chunk) + bool(pages[-1])
            if pages[-1] and size + addition > capacity:
                pages.append([])
                size = 0
                addition = len(chunk)
            pages[-1].append(chunk)
            size += addition
    return pages, prefix, suffix


def render(sections, heading, notice, tool, number):
    pages, prefix, suffix = _plan(sections, heading, notice, tool)
    if number > len(pages):
        raise ValueError(f"invalid qualified source part: total {len(pages)}")
    result = prefix(number, len(pages)) + "\n".join(pages[number - 1]) + suffix(number, len(pages))
    assert len(result) <= ASSEMBLY_PART_CHARS
    return result
