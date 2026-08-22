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
    ComponentType,
    DesignToken,
    ExtractedComponent,
    FunctionBoundary,
    InteractionEntry,
    InteractionTrigger,
    StyleEntry,
    StyleState,
    TextEntry,
    TextType,
)
from design_graph.core.patterns import (
    RE_BUTTON_TEXT,
    RE_CLASS_NAME,
    RE_COMP_REF,
    RE_HEADING,
    RE_JSX_MARKER_COMP,
    RE_JSX_TAG,
    RE_LABEL_TEXT,
    RE_NATIVE_HTML_TAG,
    RE_PLACEHOLDER,
    RE_STYLE_MUTATION,
    RE_STYLE_SPREAD,
    RE_TOOLTIP_TEXT,
    RE_TRANSITION,
    RE_UI_STRING,
    RE_USE_STATE_BOOL,
    re_event_handler_open,
    re_state_setter_trigger,
    re_state_ternary_style,
)
from design_graph.extraction.icon_extractor import extract_icons
from design_graph.extraction.jsx_sanitizer import sanitize_jsx
from design_graph.extraction.prop_extractor import extract_props_from_function_signature
from design_graph.extraction.visual_function import VisualFunctionCandidate
from design_graph.parsing.css_class_resolver import CssRule, resolve_classes
from design_graph.parsing.js_parser import (
    extract_return_block,
    find_matching_delimiter,
    iter_style_object_blocks,
    parse_object_literal_props,
)
from design_graph.parsing.palette_extractor import PrototypePalette

logger = logging.getLogger(__name__)


def select_renderable_boundaries(
    js: str, boundaries: list[FunctionBoundary],
) -> list[FunctionBoundary]:
    """Keep only functions proven to produce visual output."""
    return [
        boundary for boundary in boundaries
        if VisualFunctionCandidate.from_source(js, boundary).renders_visual_output
    ]

_COMPONENT_TYPE_MAP: list[tuple[list[str], ComponentType]] = [
    (["modal", "dialog", "confirm", "alert"],          ComponentType.MODAL),
    (["page", "screen", "dashboard"],                  ComponentType.SCREEN),
    (["btn", "button"],                                ComponentType.BUTTON),
    (["card", "tile", "widget", "section"],            ComponentType.CARD),
    (["tab", "panel"],                                 ComponentType.TAB),
    (["form", "input", "field", "select"],             ComponentType.FORM),
    (["row", "item", "list"],                          ComponentType.LIST_ITEM),
    (["badge", "pill", "tag", "dot"],                  ComponentType.BADGE),
    (["chart", "graph", "sparkline"],                  ComponentType.CHART),
    (["drawer", "sidebar", "nav"],                     ComponentType.NAVIGATION),
    (["toggle", "switch"],                             ComponentType.TOGGLE),
]

_RE_PASCAL_SPLIT = re.compile(r'(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])')


def _pascal_words_reversed(name: str) -> list[str]:
    """Split PascalCase name into lowercase words, last word first.

    Example: "ConfirmButton" → ["button", "confirm"]
    The last word carries the primary semantic type ("Button" beats "Confirm").
    """
    words = _RE_PASCAL_SPLIT.split(name)
    return [w.lower() for w in reversed(words) if w]


def infer_component_type(name: str) -> ComponentType:
    """Map a PascalCase component name to a semantic type.

    Checks each PascalCase word individually (last word first) so that the
    type-suffix wins over incidental prefix keywords.
    E.g. "ConfirmButton" → BUTTON, not MODAL from "confirm".
    """
    for word in _pascal_words_reversed(name):
        for keywords, comp_type in _COMPONENT_TYPE_MAP:
            if word in keywords:
                return comp_type
    return ComponentType.COMPONENT


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
    tag_rule_map: dict[str, dict[str, list[CssRule]]] | None = None,
    palette: PrototypePalette | None = None,
) -> ExtractedComponent:
    """
    Extract all data for one component in a single pass over its function body.

    The window is js[boundary.start:boundary.end] — exactly the function,
    no overlap with siblings.

    rule_map: optional CSS class resolver map from css_class_resolver.extract_css_rules().
    When provided, className strings are resolved into additional StyleEntry objects.

    tag_rule_map: optional map from css_class_resolver.extract_tag_pseudo_rules().
    When provided, native HTML tags the component renders (<input>, <select>, ...)
    are resolved against bare tag+pseudo-class stylesheet rules (input:focus { ... })
    into additional StyleEntry objects — independent of rule_map, which is keyed by
    className and can't answer "does this element carry that class" from CSS alone.

    palette: optional PrototypePalette from parsing.palette_extractor. When
    provided, a style value written as a direct palette reference
    (`background: C.bg`) is folded to its literal hex (`#404040`) before
    being stored — the same value a literal `background: '#404040'` would
    have produced, so existing exact-value token matching sees it too.
    """
    window = js[boundary.start : boundary.end]

    # ── JSX snippet (extracted from return block) ──
    # Icons are pulled out before sanitize_jsx so the sanitizer — and every
    # downstream consumer of jsx_snippet — only ever sees the short marker,
    # never the raw SVG source.
    jsx_raw = extract_return_block(js, boundary.start, boundary.end)
    jsx_with_icon_refs, icons = extract_icons(jsx_raw) if jsx_raw else ("", [])
    jsx_snippet = sanitize_jsx(jsx_with_icon_refs) if jsx_with_icon_refs else ""
    marker_refs = _extract_marker_refs(jsx_snippet)

    # ── Single pass: collect everything ──
    styles:       list[StyleEntry]       = []
    interactions: list[InteractionEntry] = []
    texts:        list[TextEntry]        = []
    classes:      list[str]              = []
    child_refs:   list[str]              = []  # first-appearance order, not alphabetical — see order_index (C30)

    seen_child_refs:  set[str] = set()
    seen_style_ids:   set[str] = set()
    seen_inter_ids:   set[str] = set()
    seen_text_ids:    set[str] = set()
    seen_class_strs:  set[str] = set()

    def _add_literal_style(prop: str, raw_val: str) -> bool:
        """Validate + append one `prop: value` pair as a default-state
        StyleEntry; returns whether it was actually added (kept out of the
        reserved-value skip list and not a duplicate). A direct palette
        reference (`C.bg`) is folded to its literal hex first, when the
        prototype's palette is known — the same value a literal color
        would have produced, so it's stored and matched identically."""
        val = raw_val.strip().rstrip(",").strip()
        if not val or val in ("true", "false", "null", "undefined", "inherit"):
            return False
        if palette is not None:
            resolved = palette.resolve_reference(val)
            if resolved is not None:
                val = resolved
        entry = StyleEntry.create(element=boundary.name, property=prop, value=val)
        if entry.id in seen_style_ids:
            return False
        seen_style_ids.add(entry.id)
        styles.append(entry)
        return True

    # Inline styles → StyleEntry (default state). A `...identifier` spread
    # inside the block (`style={{...inputStyle, width: 34}}`) resolves
    # against `const identifier = { ... }` found anywhere in the file —
    # shared style objects are usually declared once at module scope, not
    # inside the component that spreads them — with local properties in
    # the same block taking precedence over the same property name coming
    # from the spread (JS's own semantics for `{...base, override}`).
    for style_block in iter_style_object_blocks(window):
        if len(styles) >= MAX_STYLES_PER_COMPONENT:
            break
        local_props = parse_object_literal_props(style_block)
        for prop, val in local_props:
            _add_literal_style(prop, val)

        already_resolved = {prop for prop, _ in local_props}
        for spread_name in RE_STYLE_SPREAD.findall(style_block):
            # near_offset=boundary.end, not boundary.start: a same-named const
            # declared *inside* this component's own body (the common local-
            # scope pattern, as opposed to a module-level shared object) sits
            # textually after boundary.start — using boundary.start here would
            # wrongly exclude the component's own declaration as "not
            # preceding" and fall through to an unrelated component's object.
            spread_body = _find_const_object_body(js, spread_name, near_offset=boundary.end)
            if spread_body is None:
                continue
            for prop, val in parse_object_literal_props(spread_body):
                if prop in already_resolved:
                    continue
                if _add_literal_style(prop, val):
                    already_resolved.add(prop)

    # Hover interactions — value may be a quoted literal, a token/prop reference
    # (C.red, o.color), or a small expression (color + '12'); _clean_style_value
    # strips a fully-wrapping quote pair and leaves everything else as-is.
    # _handler_mutations scans each handler's own balanced-brace body, so a
    # multi-statement handler (`e => { style.a = X; style.b = Y; }`) yields
    # every mutation, not just the first.
    enters = [(prop, _clean_style_value(val)) for prop, val in _handler_mutations(window, "onMouseEnter")]
    leaves = [(prop, _clean_style_value(val)) for prop, val in _handler_mutations(window, "onMouseLeave")]
    enters = [(prop, val) for prop, val in enters if val]
    leaves = [(prop, val) for prop, val in leaves if val]
    # Pair by CSS property name, not list position: onMouseLeave doesn't
    # always restore properties in the same order — or the same set — that
    # onMouseEnter set them in. zip()ing the two lists positionally could
    # cross-assign a from_val belonging to a different property, or
    # silently drop enter mutations beyond leave's length. A property with
    # no matching leave restoration gets from_val="" — same convention
    # already used by from_focus_mutation for "no from_val known" — instead
    # of a wrong value borrowed from an unrelated property.
    leave_by_prop: dict[str, str] = {}
    for prop, val in leaves:
        leave_by_prop.setdefault(prop, val)
    trans_match = RE_TRANSITION.search(window)
    transition = trans_match.group(1).strip() if trans_match else "all 0.15s"

    for prop, to_val in enters:
        if len(interactions) >= MAX_INTERACTIONS_PER_COMPONENT:
            break
        from_val = leave_by_prop.get(prop, "")
        entry = InteractionEntry.create(
            element=boundary.name, trigger=InteractionTrigger.HOVER, css_prop=prop,
            from_val=from_val, to_val=to_val, transition=transition,
        )
        if entry.id not in seen_inter_ids:
            seen_inter_ids.add(entry.id)
            interactions.append(entry)
            # Hover state style entry
            if len(styles) < MAX_STYLES_PER_COMPONENT:
                style = StyleEntry.create(
                    element=boundary.name, property=prop, value=to_val, state=StyleState.HOVER,
                )
                if style.id not in seen_style_ids:
                    seen_style_ids.add(style.id)
                    styles.append(style)

    # Focus interactions
    for prop, raw_val in _handler_mutations(window, "onFocus"):
        if len(interactions) >= MAX_INTERACTIONS_PER_COMPONENT:
            break
        focus_val = _clean_style_value(raw_val)
        if not focus_val:
            continue
        entry = InteractionEntry.from_focus_mutation(
            element=boundary.name, css_prop=prop, to_val=focus_val, transition=transition,
        )
        if entry.id not in seen_inter_ids:
            seen_inter_ids.add(entry.id)
            interactions.append(entry)

    # State-toggle hover/focus: const [hov, setHov] = useState(false); handlers
    # flip it (setHov(true)/setHov(false)) instead of mutating style directly,
    # and the style value is a ternary keyed off the state var — possibly nested
    # inside a template literal (`border: \`1px solid ${hov ? A : B}\``). window
    # is exactly this component's body, so correlating the state var by name is
    # safe even though names like "hov"/"h" repeat across unrelated components.
    for state, setter in RE_USE_STATE_BOOL.findall(window):
        if len(interactions) >= MAX_INTERACTIONS_PER_COMPONENT:
            break
        has_enter = re_state_setter_trigger(setter, "onMouseEnter").search(window)
        has_leave = re_state_setter_trigger(setter, "onMouseLeave").search(window)
        if has_enter and has_leave:
            state_trigger = InteractionTrigger.HOVER
        elif re_state_setter_trigger(setter, "onFocus").search(window):
            state_trigger = InteractionTrigger.FOCUS
        else:
            continue
        for prop, to_raw, from_raw in re_state_ternary_style(state).findall(window):
            if len(interactions) >= MAX_INTERACTIONS_PER_COMPONENT:
                break
            to_val = _clean_style_value(to_raw)
            from_val = _clean_style_value(from_raw)
            if not to_val or not from_val:
                continue
            entry = InteractionEntry.create(
                element=boundary.name, trigger=state_trigger, css_prop=prop,
                from_val=from_val, to_val=to_val, transition=transition,
            )
            if entry.id not in seen_inter_ids:
                seen_inter_ids.add(entry.id)
                interactions.append(entry)
                if len(styles) < MAX_STYLES_PER_COMPONENT:
                    style = StyleEntry.create(
                        element=boundary.name, property=prop, value=to_val,
                        state=StyleState(state_trigger.value),
                    )
                    if style.id not in seen_style_ids:
                        seen_style_ids.add(style.id)
                        styles.append(style)

    # Text extraction
    def _add_text(content: str, text_type: TextType, element: str = "") -> None:
        c = content.strip()
        if not TextEntry.is_plausible_content(c):
            return
        entry = TextEntry.create(content=c, text_type=text_type, source=boundary.name, element=element)
        if entry.id not in seen_text_ids and len(texts) < MAX_TEXTS_PER_COMPONENT:
            seen_text_ids.add(entry.id)
            texts.append(entry)

    for m in RE_HEADING.finditer(window):     _add_text(m.group(1), TextType.HEADING, "h")
    for m in RE_BUTTON_TEXT.finditer(window): _add_text(m.group(1), TextType.BUTTON, "button")
    for m in RE_LABEL_TEXT.finditer(window):  _add_text(m.group(1), TextType.LABEL, "label")
    for m in RE_PLACEHOLDER.finditer(window): _add_text(m.group(1), TextType.PLACEHOLDER, "input")
    # Runs before the generic UI-string pass below so title/aria-label/alt text
    # wins the dedup (same content+source → same id) over being misclassified
    # as a generic "label" — the distinction matters for icon-only buttons,
    # where the tooltip is the only textual signal of what the element does.
    for m in RE_TOOLTIP_TEXT.finditer(window): _add_text(m.group(1), TextType.TOOLTIP)
    for m in RE_UI_STRING.finditer(window):
        t = m.group(1).strip()
        _add_text(t, TextType.DESCRIPTION if len(t) > 40 else TextType.LABEL)

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

    # Resolve native-tag pseudo-class CSS (input:focus { ... }) → StyleEntry,
    # by which native HTML tags the component itself renders — not by
    # className, unlike the block above.
    if tag_rule_map:
        native_tags = {m.group(1) for m in RE_NATIVE_HTML_TAG.finditer(window)}
        for tag in native_tags & tag_rule_map.keys():
            for pseudo_class, rules in tag_rule_map[tag].items():
                if pseudo_class not in (StyleState.HOVER, StyleState.FOCUS):
                    continue
                remaining_capacity = MAX_STYLES_PER_COMPONENT - len(styles)
                if remaining_capacity <= 0:
                    break
                for rule in rules[:remaining_capacity]:
                    # element carries the tag (LoginForm:input, not just
                    # LoginForm) so a component rendering two matching
                    # native tags with the same property/value doesn't
                    # collapse into one StyleEntry id — the tag is a real
                    # distinguishing fact here, not decoration.
                    entry = StyleEntry.create(
                        element=f"{boundary.name}:{tag}", property=rule.property,
                        value=rule.value, state=StyleState(pseudo_class),
                    )
                    if entry.id not in seen_style_ids:
                        seen_style_ids.add(entry.id)
                        styles.append(entry)

    # Child component references — from JSX tags and from typed markers in jsx_snippet.
    # Order is first-appearance, not alphabetical: RE_JSX_TAG matches (the
    # dominant source in real JSX) are collected fully before RE_COMP_REF and
    # marker_refs, so it's a documented approximation of true source order,
    # not a byte-exact reconstruction — the same class of approximation this
    # heuristic pipeline already accepts elsewhere (see C24/T46 on spread
    # merge order).
    def _add_child_ref(ref: str) -> None:
        if ref not in seen_child_refs:
            seen_child_refs.add(ref)
            child_refs.append(ref)

    for pattern in (RE_JSX_TAG, RE_COMP_REF):
        for m in pattern.finditer(window):
            ref = m.group(1)
            if ref not in REACT_INTERNALS and ref != boundary.name and len(ref) >= 3:
                _add_child_ref(ref)
    # Add components referenced inside conditional/list/ternary markers
    for ref in marker_refs:
        if ref not in REACT_INTERNALS and ref != boundary.name:
            _add_child_ref(ref)

    _cap = lambda count, limit: f"{count}{'[capped]' if count >= limit else ''}"
    logger.debug(
        "extract_component: %s → %s styles, %s interactions, %s texts, %d children",
        boundary.name,
        _cap(len(styles),        MAX_STYLES_PER_COMPONENT),
        _cap(len(interactions),  MAX_INTERACTIONS_PER_COMPONENT),
        _cap(len(texts),         MAX_TEXTS_PER_COMPONENT),
        len(child_refs),
    )
    # Surfaced to the graph (not just this debug log) as truncated_fields —
    # an agent reading get_component()/get_component_spec() must be able to
    # tell "this is everything" from "this is everything we kept up to the
    # cap" instead of silently trusting a partial spec as complete.
    truncated_fields = frozenset({
        field_name for field_name, count, limit in (
            ("styles",       len(styles),       MAX_STYLES_PER_COMPONENT),
            ("interactions", len(interactions), MAX_INTERACTIONS_PER_COMPONENT),
            ("texts",        len(texts),        MAX_TEXTS_PER_COMPONENT),
            ("classes",      len(classes),      MAX_CLASSES_PER_COMPONENT),
        )
        if count >= limit
    })

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
        child_refs=child_refs,
        props=props,
        icons=icons,
        truncated_fields=truncated_fields,
    )


async def extract_all_components(
    js: str,
    boundaries: list[FunctionBoundary],
    occurrences: Counter,
    token_map: dict[str, list[DesignToken]],
    concurrency: int = 8,
    rule_map: dict[str, list[CssRule]] | None = None,
    tag_rule_map: dict[str, dict[str, list[CssRule]]] | None = None,
    palette: PrototypePalette | None = None,
    on_component_extracted: Callable[[str, int, int], None] | None = None,
) -> list[ExtractedComponent]:
    """
    Extract all components concurrently using asyncio.to_thread.

    The JS string is immutable — concurrent reads are safe.
    Each task produces an independent ExtractedComponent — no shared writes.
    rule_map: optional CSS class resolver map forwarded to each extract_component call.
    tag_rule_map: optional native-tag pseudo-class map, same forwarding.
    palette: optional PrototypePalette forwarded to each extract_component call —
        see extract_component's own docstring.
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
                js, boundary, occurrences.get(boundary.name, 1), token_map,
                rule_map, tag_rule_map, palette,
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

    # Same-named definitions are source variants; preserve their combined evidence.
    variants_by_name: dict[str, list[ExtractedComponent]] = {}
    for comp in results:
        variants_by_name.setdefault(comp.name, []).append(comp)
    unique = [
        ExtractedComponent.consolidate(variants)
        for variants in variants_by_name.values()
    ]

    unique.sort(key=lambda c: -c.occurrence)
    logger.info("extract_all_components: extracted %d unique components", len(unique))
    return unique


# ── Private helpers ───────────────────────────────────────────────────────────

def _find_const_object_body(js: str, name: str, near_offset: int = 0) -> str | None:
    """
    The inner text of `const <name> = { ... }`, or None if no such
    declaration exists in js. Searches the whole file, not just one
    component's window — shared style objects are normally declared once
    at module scope and referenced by spread from several components.

    A minified/bundled file sometimes repeats a generic name (`style`,
    `cardStyle`) as a *local* const inside more than one component's own
    scope — always taking the first declaration in the file would then
    resolve a component's spread against a completely unrelated
    component's object. Among every declaration of `name`, the one closest
    to (and at or before) near_offset — normally the spreading component's
    own boundary.end, so a declaration local to that component's own body
    is preferred over one belonging to an unrelated, later component — is
    preferred, matching how JS scoping would actually resolve the
    reference. Falls back to the first declaration in the file when none
    precedes near_offset.
    """
    matches = list(re.finditer(rf'\bconst\s+{re.escape(name)}\s*=\s*\{{', js))
    if not matches:
        return None
    preceding = [m for m in matches if m.start() <= near_offset]
    decl = preceding[-1] if preceding else matches[0]
    open_brace = decl.end() - 1
    region_end = find_matching_delimiter(js, open_brace, "{", "}")
    if region_end is None:
        return None
    return js[open_brace + 1 : region_end - 1]


def _handler_mutations(window: str, event: str) -> list[tuple[str, str]]:
    """
    All `style.prop = value` mutations inside every <event>={...} handler in
    window. Isolates each handler's own balanced-brace body first, so a
    multi-statement handler (`e => { style.a = X; style.b = Y; }`) yields
    every mutation instead of only the first `style.` assignment in window.
    """
    mutations: list[tuple[str, str]] = []
    for m in re_event_handler_open(event).finditer(window):
        brace_index = m.end() - 1
        end = find_matching_delimiter(window, brace_index, "{", "}")
        body = window[brace_index + 1:end - 1] if end is not None else window[brace_index + 1:brace_index + 300]
        mutations.extend(RE_STYLE_MUTATION.findall(body))
    return mutations


def _clean_style_value(raw: str) -> str:
    """
    Normalize a captured `style.prop = <raw>` right-hand side.

    Strips a fully-wrapping quote pair ('#333' -> #333) so literal colors
    render the same as before this pattern also matched identifiers and
    expressions (C.red, o.color + '0c') — those are returned unquoted/as-is
    since there is nothing meaningful to unwrap.
    """
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1].strip()
    return value
