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
from typing import Callable

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
    RE_JSX_MAP_RENDER,
    RE_JSX_MARKER_COMP,
    RE_JSX_SHORT_CIRCUIT,
    RE_JSX_TAG,
    RE_JSX_TERNARY_COMPONENTS,
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
from design_graph.extraction.prop_extractor import extract_props_from_function_signature
from design_graph.parsing.css_class_resolver import CssRule, resolve_classes
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

_RE_PASCAL_SPLIT = re.compile(r'(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])')


def _pascal_words_reversed(name: str) -> list[str]:
    """Split PascalCase name into lowercase words, last word first.

    Example: "ConfirmButton" → ["button", "confirm"]
    The last word carries the primary semantic type ("Button" beats "Confirm").
    """
    words = _RE_PASCAL_SPLIT.split(name)
    return [w.lower() for w in reversed(words) if w]


def infer_component_type(name: str) -> str:
    """Map a PascalCase component name to a semantic type string.

    Checks each PascalCase word individually (last word first) so that the
    type-suffix wins over incidental prefix keywords.
    E.g. "ConfirmButton" → "button", not "modal" from "confirm".
    """
    for word in _pascal_words_reversed(name):
        for keywords, comp_type in _COMPONENT_TYPE_MAP:
            if word in keywords:
                return comp_type
    return "component"


def sanitize_jsx(jsx: str) -> str:
    """
    Strip JavaScript logic from JSX, replacing dynamic expressions with
    typed markers that preserve structural information for AI agents:

      {[list:ComponentName]}           — .map() list rendering
      {[conditional:ComponentName]}    — short-circuit && rendering
      {[either:ComponentA|ComponentB]} — ternary between components

    Static content, tags, inline styles, and component names are preserved.
    """
    # 1. Collapse long event handlers: onClick={() => doSomethingLong()} → on[handler]
    jsx = RE_LONG_EVENT_HANDLER.sub("on[handler]", jsx)

    # 2. Collapse long arrow functions in method chains
    jsx = RE_LONG_ARROW_FN.sub(".[fn]", jsx)

    # 3. List rendering: {arr.map(item => <Comp />)} → {[list:Comp]}
    n_list = [0]
    def _list_marker(m: re.Match) -> str:
        n_list[0] += 1
        return f"{{[list:{m.group(1)}]}}"
    jsx = RE_JSX_MAP_RENDER.sub(_list_marker, jsx)

    # 4. Short-circuit conditional: {flag && <Comp />} → {[conditional:Comp]}
    n_conditional = [0]
    def _conditional_marker(m: re.Match) -> str:
        n_conditional[0] += 1
        return f"{{[conditional:{m.group(1)}]}}"
    jsx = RE_JSX_SHORT_CIRCUIT.sub(_conditional_marker, jsx)

    # 5. Ternary between components: {cond ? <A /> : <B />} → {[either:A|B]}
    n_ternary = [0]
    def _ternary_marker(m: re.Match) -> str:
        n_ternary[0] += 1
        return f"{{[either:{m.group(1)}|{m.group(2)}]}}"
    jsx = RE_JSX_TERNARY_COMPONENTS.sub(_ternary_marker, jsx)

    # 6. Collapse remaining long style objects: style={{ ... (>400 chars) }}
    def _collapse_long_style(m: re.Match) -> str:
        inner = m.group(0)
        if len(inner) <= 400:
            return inner
        props = RE_STYLE_PROP.findall(inner)[:6]
        preview = ", ".join(f"{k}: {v.strip()}" for k, v in props)
        return f"style={{{{ {preview}, ... }}}}"
    jsx = re.sub(r"style=\{\{[^}]{200,}\}\}", _collapse_long_style, jsx)

    # 7. Collapse remaining very long expressions (fallback — anything > 300 chars)
    jsx = RE_LONG_TERNARY.sub("{...}", jsx)

    # 8. Normalize whitespace
    jsx = re.sub(r"\n{3,}", "\n\n", jsx)

    if n_list[0] or n_conditional[0] or n_ternary[0]:
        logger.debug(
            "sanitize_jsx: inserted %d list, %d conditional, %d ternary markers",
            n_list[0], n_conditional[0], n_ternary[0],
        )

    return jsx.strip()


def _extract_marker_refs(sanitized_jsx: str) -> set[str]:
    """
    Extract PascalCase component names referenced inside typed JSX markers.
    Handles {[list:Comp]}, {[conditional:Comp]}, {[either:CompA|CompB]}.
    """
    refs: set[str] = set()
    for m in RE_JSX_MARKER_COMP.finditer(sanitized_jsx):
        for name in m.group(1).split("|"):
            name = name.strip()
            if name and len(name) >= 3:
                refs.add(name)
    return refs


def extract_component(
    js: str,
    boundary: FunctionBoundary,
    occurrence: int,
    token_map: dict[str, list[DesignToken]],
    rule_map: dict[str, list[CssRule]] | None = None,
) -> ExtractedComponent:
    """
    Extract all data for one component in a single pass over its function body.

    The window is js[boundary.start:boundary.end] — exactly the function,
    no overlap with siblings.

    rule_map: optional CSS class resolver map from css_class_resolver.extract_css_rules().
    When provided, className strings are resolved into additional StyleEntry objects.
    """
    window = js[boundary.start : boundary.end]

    # ── JSX snippet (extracted from return block) ──
    jsx_raw = extract_return_block(js, boundary.start, boundary.end)
    jsx_snippet = sanitize_jsx(jsx_raw) if jsx_raw else ""
    marker_refs = _extract_marker_refs(jsx_snippet)

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

    # Resolve CSS class names → additional StyleEntry objects
    if rule_map is not None and classes:
        class_string = " ".join(classes)
        class_styles = resolve_classes(class_string, rule_map)
        remaining_capacity = MAX_STYLES_PER_COMPONENT - len(styles)
        if remaining_capacity > 0:
            for cs in class_styles[:remaining_capacity]:
                if cs.id not in seen_style_ids:
                    seen_style_ids.add(cs.id)
                    styles.append(cs)

    # Child component references — from JSX tags and from typed markers in jsx_snippet
    for pattern in (RE_JSX_TAG, RE_COMP_REF):
        for m in pattern.finditer(window):
            ref = m.group(1)
            if ref not in REACT_INTERNALS and ref != boundary.name and len(ref) >= 3:
                child_refs.add(ref)
    # Add components referenced inside conditional/list/ternary markers
    for ref in marker_refs:
        if ref not in REACT_INTERNALS and ref != boundary.name:
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

    props = extract_props_from_function_signature(js, boundary)

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
        props=props,
    )


async def extract_all_components(
    js: str,
    boundaries: list[FunctionBoundary],
    occurrences: Counter,
    token_map: dict[str, list[DesignToken]],
    concurrency: int = 8,
    rule_map: dict[str, list[CssRule]] | None = None,
    on_component_extracted: Callable[[str, int, int], None] | None = None,
) -> list[ExtractedComponent]:
    """
    Extract all components concurrently using asyncio.to_thread.

    The JS string is immutable — concurrent reads are safe.
    Each task produces an independent ExtractedComponent — no shared writes.
    rule_map: optional CSS class resolver map forwarded to each extract_component call.
    on_component_extracted: optional callback(name, index, total) called once per
        completed extraction in the asyncio event loop — safe for non-thread-safe
        reporters since asyncio is single-threaded.
    """
    if not boundaries:
        return []

    semaphore = asyncio.Semaphore(concurrency)
    total = len(boundaries)
    completed = [0]

    async def _extract_with_guard(boundary: FunctionBoundary) -> ExtractedComponent:
        async with semaphore:
            result = await asyncio.to_thread(
                extract_component,
                js, boundary, occurrences.get(boundary.name, 1), token_map, rule_map,
            )
        completed[0] += 1
        if on_component_extracted is not None:
            try:
                on_component_extracted(boundary.name, completed[0], total)
            except Exception:  # noqa: BLE001
                logger.debug(
                    "extract_all_components: on_component_extracted raised for %s — ignored",
                    boundary.name,
                )
        return result

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
