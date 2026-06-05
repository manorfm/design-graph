"""
HTML prototype chunker — converts extracted entities into AI-ready fragments.

Each ChunkEnvelope is self-contained: it includes a breadcrumb, parent/sibling
references, and a one-line context summary so an AI can understand its place in
the prototype without loading the entire document.

Chunking hierarchy: Screen > Section > Component
When a section's content exceeds max_chars, it is broken into per-component chunks.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
from pathlib import Path

from design_graph.core.constants import CHUNK_CHARS_PER_TOKEN, DEFAULT_CHUNK_MAX_CHARS
from design_graph.core.models import (
    ChunkEnvelope,
    ExtractedComponent,
    ExtractedScreen,
    ExtractedSection,
)
from design_graph.core.patterns import RE_CHUNK_ID_INVALID

logger = logging.getLogger(__name__)


def chunk_extracted_data(
    screens: list[ExtractedScreen],
    sections: dict[str, list[ExtractedSection]],
    components: dict[str, ExtractedComponent],
    max_chars: int = DEFAULT_CHUNK_MAX_CHARS,
) -> list[ChunkEnvelope]:
    """
    Build a hierarchical list of ChunkEnvelopes from extracted prototype data.

    Strategy:
    - Screen without sections → 1 chunk containing component JSX snippets
    - Screen with small sections → 1 chunk per section
    - Screen with large sections → break into per-component chunks
    """
    result: list[ChunkEnvelope] = []
    used_ids: set[str] = set()

    for screen in screens:
        screen_id   = _unique_chunk_id(screen.name, used_ids)
        screen_secs = sections.get(screen.name, [])

        if not screen_secs:
            content = _build_screen_content(screen, components, max_chars)
            if content:
                result.append(ChunkEnvelope(
                    chunk_id=screen_id,
                    breadcrumb=screen.name,
                    level="screen",
                    parent_id=None,
                    sibling_ids=[],
                    child_ids=[],
                    content=content,
                    tokens_est=len(content) // CHUNK_CHARS_PER_TOKEN,
                    component_refs=screen.component_refs,
                    context_summary=_screen_summary(screen),
                    source_screen=screen.name,
                ))
            continue

        # Pre-compute section chunk IDs so siblings can reference each other
        sec_ids = [_unique_chunk_id(f"{screen.name}__{s.name}", used_ids) for s in screen_secs]

        section_chunks: list[ChunkEnvelope] = []
        for i, section in enumerate(screen_secs):
            siblings = [sid for j, sid in enumerate(sec_ids) if j != i]

            if len(section.jsx_snippet) <= max_chars:
                cid = sec_ids[i]
                chunk = ChunkEnvelope(
                    chunk_id=cid,
                    breadcrumb=f"{screen.name} > {section.name}",
                    level="section",
                    parent_id=screen_id,
                    sibling_ids=siblings,
                    child_ids=[],
                    content=section.jsx_snippet or _section_fallback_content(section),
                    tokens_est=len(section.jsx_snippet) // CHUNK_CHARS_PER_TOKEN,
                    component_refs=section.component_refs,
                    context_summary=_section_summary(section, screen.name),
                    source_screen=screen.name,
                )
                if chunk.content:
                    section_chunks.append(chunk)
            else:
                # Section too large — break into component-level chunks
                comp_chunks = _split_section_by_components(
                    section=section,
                    components=components,
                    screen_name=screen.name,
                    parent_id=sec_ids[i],
                    section_siblings=siblings,
                    used_ids=used_ids,
                    max_chars=max_chars,
                )
                section_chunks.extend(comp_chunks)

        # Add child_ids to screen chunk (if screen chunk is added)
        child_ids = [c.chunk_id for c in section_chunks]
        result.append(ChunkEnvelope(
            chunk_id=screen_id,
            breadcrumb=screen.name,
            level="screen",
            parent_id=None,
            sibling_ids=[],
            child_ids=child_ids,
            content=f"Screen {screen.name} with {len(screen_secs)} sections.",
            tokens_est=1,
            component_refs=screen.component_refs,
            context_summary=_screen_summary(screen),
            source_screen=screen.name,
        ))
        result.extend(section_chunks)

    logger.info("chunker: generated %d chunks from %d screens", len(result), len(screens))
    return result


def export_chunks_jsonl(chunks: list[ChunkEnvelope], output_path: Path) -> None:
    """Write one JSON object per line. Creates the parent directory if needed."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(dataclasses.asdict(chunk), ensure_ascii=False) + "\n")
    logger.debug("chunker: exported %d chunks to %s", len(chunks), output_path)


# ── Chunk ID generation ───────────────────────────────────────────────────────

def to_chunk_id(name: str) -> str:
    """
    Convert any string to a valid slug: [a-z0-9_]+.
    CamelCase is split into snake_case before lowercasing.
    """
    # Insert underscore before uppercase letters (CamelCase → snake_case)
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    name = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", name)
    slug = RE_CHUNK_ID_INVALID.sub("_", name.lower()).strip("_")
    slug = re.sub(r"_+", "_", slug)
    return slug or "chunk"


def _unique_chunk_id(name: str, used_ids: set[str]) -> str:
    """Generate a slug and append a counter suffix if already used."""
    base = to_chunk_id(name)
    cid  = base
    n    = 1
    while cid in used_ids:
        cid = f"{base}_{n}"
        n  += 1
    used_ids.add(cid)
    return cid


# ── Content builders ──────────────────────────────────────────────────────────

def _build_screen_content(
    screen: ExtractedScreen,
    components: dict[str, ExtractedComponent],
    max_chars: int,
) -> str:
    """Build content for a screen that has no detected sections."""
    parts: list[str] = []
    total = 0
    for comp_name in screen.component_refs[:5]:
        comp = components.get(comp_name)
        if comp and comp.jsx_snippet:
            snippet = comp.jsx_snippet
            if total + len(snippet) > max_chars:
                break
            parts.append(f"/* {comp_name} */\n{snippet}")
            total += len(snippet)

    if parts:
        return "\n\n".join(parts)

    # Fallback: at minimum describe what the screen renders
    refs = ", ".join(screen.component_refs[:8]) or "none"
    return f"/* Screen: {screen.name} | components: {refs} */"


def _section_fallback_content(section: ExtractedSection) -> str:
    """Generate minimal content when jsx_snippet is empty."""
    refs = ", ".join(section.component_refs[:5]) or "none"
    return f"/* Section: {section.name} | components: {refs} */"


def _split_section_by_components(
    section: ExtractedSection,
    components: dict[str, ExtractedComponent],
    screen_name: str,
    parent_id: str,
    section_siblings: list[str],
    used_ids: set[str],
    max_chars: int,
) -> list[ChunkEnvelope]:
    """Break an oversized section into per-component chunks."""
    chunks: list[ChunkEnvelope] = []

    for comp_name in section.component_refs:
        comp = components.get(comp_name)
        content = (comp.jsx_snippet if comp else "")[:max_chars]
        if not content:
            content = f"/* {comp_name} — no JSX available */"

        cid = _unique_chunk_id(f"{screen_name}__{section.name}__{comp_name}", used_ids)
        chunks.append(ChunkEnvelope(
            chunk_id=cid,
            breadcrumb=f"{screen_name} > {section.name} > {comp_name}",
            level="component",
            parent_id=parent_id,
            sibling_ids=section_siblings,
            child_ids=[],
            content=content,
            tokens_est=len(content) // CHUNK_CHARS_PER_TOKEN,
            component_refs=[comp_name],
            context_summary=f"Componente {comp_name} da seção {section.name} em {screen_name}",
            source_screen=screen_name,
        ))

    return chunks


# ── Summary generators ────────────────────────────────────────────────────────

def _screen_summary(screen: ExtractedScreen) -> str:
    return (
        f"Tela {screen.name} com {len(screen.component_refs)} componentes "
        f"em {screen.sections_count} seções"
    )


def _section_summary(section: ExtractedSection, screen_name: str) -> str:
    comps = ", ".join(section.component_refs[:3])
    suffix = f" — componentes: {comps}" if comps else ""
    return f"Seção {section.name} da tela {screen_name}{suffix}"
