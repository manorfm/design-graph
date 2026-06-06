"""
Single-pass React component extractor.

Replaces the 5× redundant scan in the legacy build_graph.py by traversing
each function body exactly once and collecting styles, interactions, texts,
class names, and child component references in a single pass.

Concurrency: extract_all_components uses asyncio.to_thread so that CPU-bound
regex work runs in a thread pool. The JS string is immutable (Python str),
so concurrent reads are safe. Each component gets its own ExtractedComponent
instance — no shared mutable state.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections import Counter

from design_graph.core.constants import (
    MAX_CLASSES_PER_COMPONENT,
    MAX_INTERACTIONS_PER_COMPONENT,
    MAX_STYLES_PER_COMPONENT,
    MAX_TEXTS_PER_COMPONENT,
    REACT_INTERNALS,
)
from design_graph.core.models import (
    DesignToken,
    ExtractedComponent,
    FunctionBoundary,
    InteractionEntry,
    StyleEntry,
    TextEntry,
)
from design_graph.core.patterns import (
    RE_BUTTON_TEXT,
    RE_CLASS_NAME,
    RE_COMP_REF,
    RE_HEADING,
    RE_INLINE_STYLE,
    RE_JSX_TAG,
    RE_LABEL_TEXT,
    RE_LONG_ARROW_FN,
    RE_LONG_EVENT_HANDLER,
    RE_LONG_TERNARY,
    RE_MOUSE_ENTER,
    RE_MOUSE_LEAVE,
    RE_ON_FOCUS,
    RE_PLACEHOLDER,
    RE_STYLE_PROP,
    RE_TRANSITION,
    RE_UI_STRING,
)
from design_graph.parsing.js_parser import extract_return_block

logger = logging.getLogger(__name__)

_COMPONENT_TYPE_MAP: list[tuple[list[str], str]] = [
    (["modal", "dialog", "confirm", "alert"],          "modal"),
    (["page", "screen", "dashboard"],                  "screen"),
    (["btn", "button"],                                "button"),
    (["card", "tile", "widget", "section"],            "card"),
    (["tab", "panel"],                                 "tab"),
    (["form", "input", "field", "select"],             "form"),
    (["row", "item", "list"],                          "list-item"),
    (["badge", "pill", "tag", "dot"],                  "badge"),
    (["chart", "graph", "sparkline"],                  "chart"),
    (["drawer", "sidebar", "nav"],                     "navigation"),
    (["toggle", "switch"],                             "toggle"),
]


def infer_component_type(name: str) -> str:
    """Map a PascalCase component name to a semantic type string."""
    lowered = name.lower()
    for keywords, comp_type in _COMPONENT_TYPE_MAP:
        if any(kw in lowered for kw in keywords):
            return comp_type
    return "component"


def sanitize_jsx(jsx: str) -> str:
    """
    Strip JavaScript logic from JSX, keeping only visual structure:
    tags, hierarchy, inline styles, text, and child component names.
    """
    jsx = RE_LONG_EVENT_HANDLER.sub("on[handler]", jsx)
    jsx = RE_LONG_ARROW_FN.sub(".[fn]", jsx)

    def _collapse_long_style(m: re.Match) -> str:
        inner = m.group(0)
        if len(inner) <= 400:
            return inner
        props = RE_STYLE_PROP.findall(inner)[:6]
        preview = ", ".join(f"{k}: {v.strip()}" for k, v in props)
        return f"style={{{{ {preview}, ... }}}}"

    jsx = re.sub(r"style=\{\{[^}]{200,}\}\}", _collapse_long_style, jsx)
    jsx = RE_LONG_TERNARY.sub("{...}", jsx)
    jsx = re.sub(r"\n{3,}", "\n\n", jsx)
    return jsx.strip()


def extract_component(
    js: str,
    boundary: FunctionBoundary,
    occurrence: int,
    token_map: dict[str, list[DesignToken]],
) -> ExtractedComponent:
    """
    Extract all data for one component in a single pass over its function body.

    The window is js[boundary.start:boundary.end] — exactly the function,
    no overlap with siblings.
    """
    window = js[boundary.start : boundary.end]

    # ── JSX snippet (extracted from return block) ──
    jsx_raw = extract_return_block(js, boundary.start, boundary.end)
    jsx_snippet = sanitize_jsx(jsx_raw) if jsx_raw else ""

    # ── Single pass: collect everything ──
    styles:       list[StyleEntry]       = []
    interactions: list[InteractionEntry] = []
    texts:        list[TextEntry]        = []
    classes:      list[str]              = []
    child_refs:   set[str]               = set()

    seen_style_ids:   set[str] = set()
    seen_inter_ids:   set[str] = set()
    seen_text_ids:    set[str] = set()
    seen_class_strs:  set[str] = set()

    # Inline styles → StyleEntry (default state)
    for sm in RE_INLINE_STYLE.finditer(window):
        if len(styles) >= MAX_STYLES_PER_COMPONENT:
            break
        for prop, val in RE_STYLE_PROP.findall(sm.group(1)):
            val = val.strip().rstrip(",").strip()
            if not val or val in ("true", "false", "null", "undefined", "inherit"):
                continue
            sid = _hid(f"{boundary.name}_{prop}_{val}", "st_")
            if sid not in seen_style_ids:
                seen_style_ids.add(sid)
                styles.append(StyleEntry(
                    id=sid, element=boundary.name, state="default",
                    property=prop, value=val,
                ))

    # Hover interactions
    enters = RE_MOUSE_ENTER.findall(window)
    leaves = RE_MOUSE_LEAVE.findall(window)
    trans_match = RE_TRANSITION.search(window)
    transition = trans_match.group(1).strip() if trans_match else "all 0.15s"

    for (prop, to_val), (_, from_val) in zip(enters, leaves):
        if len(interactions) >= MAX_INTERACTIONS_PER_COMPONENT:
            break
        iid = _hid(f"{boundary.name}_{prop}_{to_val}", "int_")
        if iid not in seen_inter_ids:
            seen_inter_ids.add(iid)
            interactions.append(InteractionEntry(
                id=iid, trigger="hover", css_prop=prop,
                from_val=from_val, to_val=to_val, transition=transition,
            ))
            # Hover state style entry
            if len(styles) < MAX_STYLES_PER_COMPONENT:
                hsid = _hid(f"{boundary.name}_hover_{prop}_{to_val}", "st_")
                if hsid not in seen_style_ids:
                    seen_style_ids.add(hsid)
                    styles.append(StyleEntry(
                        id=hsid, element=boundary.name, state="hover",
                        property=prop, value=to_val,
                    ))

    # Focus interactions
    for m in RE_ON_FOCUS.finditer(window):
        if len(interactions) >= MAX_INTERACTIONS_PER_COMPONENT:
            break
        iid = _hid(f"{boundary.name}_focus_{m.group(1)}", "int_")
        if iid not in seen_inter_ids:
            seen_inter_ids.add(iid)
            interactions.append(InteractionEntry(
                id=iid, trigger="focus", css_prop=m.group(1),
                from_val="", to_val=m.group(2), transition=transition,
            ))

    # Text extraction
    def _add_text(content: str, text_type: str, element: str = "") -> None:
        c = content.strip()
        if not c or len(c) < 3 or len(c) > 80:
            return
        if re.match(r"^[a-z_]+$", c) or c.startswith(("#", "rgba")):
            return
        tid = _hid(f"{boundary.name}_{c}", "txt_")
        if tid not in seen_text_ids and len(texts) < MAX_TEXTS_PER_COMPONENT:
            seen_text_ids.add(tid)
            texts.append(TextEntry(
                id=tid, content=c,
                text_type=text_type, source=boundary.name, element=element,
            ))

    for m in RE_HEADING.finditer(window):     _add_text(m.group(1), "heading", "h")
    for m in RE_BUTTON_TEXT.finditer(window): _add_text(m.group(1), "button", "button")
    for m in RE_LABEL_TEXT.finditer(window):  _add_text(m.group(1), "label", "label")
    for m in RE_PLACEHOLDER.finditer(window): _add_text(m.group(1), "placeholder", "input")
    for m in RE_UI_STRING.finditer(window):
        t = m.group(1).strip()
        _add_text(t, "description" if len(t) > 40 else "label")

    # CSS class names
    for m in RE_CLASS_NAME.finditer(window):
        for cls in m.group(1).split():
            if cls not in seen_class_strs and len(classes) < MAX_CLASSES_PER_COMPONENT:
                seen_class_strs.add(cls)
                classes.append(cls)

    # Child component references
    for pattern in (RE_JSX_TAG, RE_COMP_REF):
        for m in pattern.finditer(window):
            ref = m.group(1)
            if ref not in REACT_INTERNALS and ref != boundary.name and len(ref) >= 3:
                child_refs.add(ref)

    _cap = lambda count, limit: f"{count}{'[capped]' if count >= limit else ''}"
    logger.debug(
        "extract_component: %s → %s styles, %s interactions, %s texts, %d children",
        boundary.name,
        _cap(len(styles),        MAX_STYLES_PER_COMPONENT),
        _cap(len(interactions),  MAX_INTERACTIONS_PER_COMPONENT),
        _cap(len(texts),         MAX_TEXTS_PER_COMPONENT),
        len(child_refs),
    )

    return ExtractedComponent(
        name=boundary.name,
        comp_type=infer_component_type(boundary.name),
        jsx_snippet=jsx_snippet,
        occurrence=occurrence,
        classes=" ".join(classes),
        styles=styles,
        interactions=interactions,
        texts=texts,
        child_refs=sorted(child_refs),
    )


async def extract_all_components(
    js: str,
    boundaries: list[FunctionBoundary],
    occurrences: Counter,
    token_map: dict[str, list[DesignToken]],
    concurrency: int = 8,
) -> list[ExtractedComponent]:
    """
    Extract all components concurrently using asyncio.to_thread.

    The JS string is immutable — concurrent reads are safe.
    Each task produces an independent ExtractedComponent — no shared writes.
    """
    if not boundaries:
        return []

    semaphore = asyncio.Semaphore(concurrency)

    async def _extract_with_guard(boundary: FunctionBoundary) -> ExtractedComponent:
        async with semaphore:
            return await asyncio.to_thread(
                extract_component,
                js, boundary, occurrences.get(boundary.name, 1), token_map,
            )

    results = await asyncio.gather(*[_extract_with_guard(b) for b in boundaries])

    # De-duplicate by name (nested function definitions can produce duplicates)
    seen: set[str] = set()
    unique: list[ExtractedComponent] = []
    for comp in results:
        if comp.name not in seen:
            seen.add(comp.name)
            unique.append(comp)

    unique.sort(key=lambda c: -c.occurrence)
    logger.info("extract_all_components: extracted %d unique components", len(unique))
    return unique


# ── Private helpers ───────────────────────────────────────────────────────────

def _hid(s: str, prefix: str = "") -> str:
    return f"{prefix}{hashlib.md5(s.encode()).hexdigest()[:8]}"
