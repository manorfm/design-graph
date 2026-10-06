"""
Components of a DC canvas, inferred from what its pages repeat.

DC pages are written out in full — nothing names a reusable piece — so a
component is a structure the author repeated: the same element (tag, the
properties it styles, its children's tags) at least MIN_REPEATS times, on one
page or across pages, or the item a <sc-for> loop repeats by construction. Only elements at or below a page's
blocks qualify; the page skeleton around the blocks is layout, not a
component.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from bs4 import Tag

from design_graph.capture.dc_canvas.sections import block_name
from design_graph.capture.dc_canvas.template import (
    INTERPOLATION,
    SOURCE_LANG,
    element_children,
    element_paths,
    inline_property_names,
    inline_styles,
    rendered_descendants,
    tag_of,
    visible_text_nodes,
)
from design_graph.capture.html_prototype.parsing.css_class_resolver import CssRule
from design_graph.model.entities import (
    ComponentType,
    ExtractedComponent,
    StyleEntry,
    StyleState,
    TextEntry,
    TextType,
)

MIN_REPEATS = 3
_MIN_DESCENDANTS = 2
_MIN_STYLED_PROPERTIES = 3
_INTERACTIVE = {"a", "button", "input", "select", "textarea"}
_TYPE_BY_TAG = {
    "nav": ComponentType.NAVIGATION, "a": ComponentType.BUTTON, "button": ComponentType.BUTTON,
    "table": ComponentType.TABLE, "form": ComponentType.FORM,
}
_TYPE_BY_ROLE = {"tab": ComponentType.TAB, "switch": ComponentType.TOGGLE, "button": ComponentType.BUTTON}
_NAME_BY_TAG = {
    "nav": "Navigation", "aside": "Sidebar", "header": "Header", "footer": "Footer", "table": "Table",
    "form": "Form", "button": "Button", "a": "Link", "input": "Input", "select": "Select", "textarea": "TextArea",
}
_TEXT_TYPE_BY_TAG = {
    **{f"h{n}": TextType.HEADING for n in range(1, 7)},
    "button": TextType.BUTTON, "a": TextType.BUTTON, "p": TextType.DESCRIPTION,
}
_STATES = {"hover": StyleState.HOVER, "focus": StyleState.FOCUS, "focus-visible": StyleState.FOCUS}
_RE_INTERPOLATION = re.compile(r"\{\{[^}]*\}\}")
_RE_LOOP_LIST = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")
_MAX_NAME_WORDS = 3
_MAX_CONTEXT_WORDS = 2
# Articles, prepositions and conjunctions carry no meaning in a name ("Convites e participação" → ConvitesParticipação).
_LITTLE_WORDS = frozenset(
    "a o as os um uma de da do das dos e ou em no na nos nas por para com que se the of and or to in on for".split()
)
_ROUND = {"50%", "999px", "9999px", "100%"}
_SVG_MARKS = ("path", "line", "polyline", "polygon", "rect", "circle", "ellipse", "text")
_ROLE_BY_TAG = {
    "td": "Cell", "th": "Cell", "tr": "Row", "li": "Item", "ul": "List", "ol": "List", "img": "Image",
    "p": "Text", "label": "Label", "svg": "Chart", **{f"h{n}": "Heading" for n in range(1, 7)},
    **{mark: "ChartMark" for mark in _SVG_MARKS},
}


@dataclass
class CanvasComponents:
    components: list[ExtractedComponent]
    name_of: dict[int, str] = field(default_factory=dict)  # id(element) → its component

    def outermost_in(self, element: Tag) -> list[str]:
        """The components at or under `element`, outermost only, each once, in order."""
        if id(element) in self.name_of:
            return [self.name_of[id(element)]]
        names: dict[str, None] = {}
        for child in element_children(element):
            names.update(dict.fromkeys(self.outermost_in(child)))
        return list(names)


TagRules = dict[str, dict[str, list[CssRule]]]  # tag → state → rules, e.g. a → hover → [color: …]
LoopData = Callable[[str, str], object]          # (screen, list name) → the list's literal value, or None


def infer_components(
    blocks_by_screen: dict[str, list[Tag]],
    tag_rules: TagRules | None = None,
    loop_data: LoopData | None = None,
) -> CanvasComponents:
    """
    tag_rules: pseudo-class rules the pages' styles declare for a bare tag
        (`a:hover`), applied to every component rendered as that tag.
    loop_data: where a loop item's list is looked up, to attach its values.
    """
    occurrences, loop_lists = _occurrences(blocks_by_screen)
    promoted = [signature for signature in occurrences if _is_repeated(signature, occurrences, loop_lists)]
    result = CanvasComponents(components=[])
    block_of = _blocks_by_element(blocks_by_screen)
    used: set[str] = set()
    for signature in promoted:
        elements = [element for _, element in occurrences[signature]]
        name = _unique(_name(elements, loop_lists.get(signature), result.name_of, block_of), used)
        result.name_of.update({id(element): name for element in elements})
    details = _Details(tag_rules or {}, loop_data or _no_loop_data)
    result.components = [
        _component(occurrences[signature], result, details, loop_lists.get(signature)) for signature in promoted
    ]
    return result


@dataclass(frozen=True)
class _Details:
    tag_rules: TagRules
    loop_data: LoopData


def fragment_component(root: Tag) -> ExtractedComponent:
    """A standalone fragment read as one component, outside any canvas."""
    found = CanvasComponents(components=[], name_of={id(root): "Fragment"})
    return _component([("", root)], found, _Details({}, _no_loop_data), None)


def _no_loop_data(screen: str, name: str) -> None:
    return None


def _is_repeated(signature: str, occurrences: dict, loop_lists: dict[str, str]) -> bool:
    """A loop item repeats by construction; anything else must recur MIN_REPEATS times, on one page or across pages."""
    return signature in loop_lists or len(occurrences[signature]) >= MIN_REPEATS


def _occurrences(
    blocks_by_screen: dict[str, list[Tag]],
) -> tuple[dict[str, list[tuple[str, Tag]]], dict[str, str]]:
    """Signature → every (screen, element) showing it, first seen first; and loop items' lists."""
    occurrences: dict[str, list[tuple[str, Tag]]] = {}
    loop_lists: dict[str, str] = {}
    for screen, blocks in blocks_by_screen.items():
        for element in (e for block in blocks for e in [block, *rendered_descendants(block)]):
            loop_list = _loop_list(element)
            if not (loop_list or _is_candidate(element)):
                continue
            signature = _signature(element)
            occurrences.setdefault(signature, []).append((screen, element))
            if loop_list:
                loop_lists.setdefault(signature, loop_list)
    return occurrences, loop_lists


def _is_candidate(element: Tag) -> bool:
    """Worth recognizing when repeated: interactive, given a role, with children of its own, or styled at length (a cell)."""
    return (
        tag_of(element) in _INTERACTIVE
        or bool(element.get("role"))
        or len(rendered_descendants(element)) >= _MIN_DESCENDANTS
        or len(inline_property_names(element)) >= _MIN_STYLED_PROPERTIES
    )


def _loop_list(element: Tag) -> str | None:
    """The list a <sc-for> repeats this element over, when it is the loop's item."""
    parent = element.parent
    if not isinstance(parent, Tag) or parent.name != "sc-for":
        return None
    found = _RE_LOOP_LIST.search(parent.get("list") or "")
    return found.group(1).split(".")[-1] if found else "Loop"


def _signature(element: Tag) -> str:
    """What a repeated piece keeps: its tag, role, which properties it styles (values may vary) and its children's tags."""
    style = ",".join(sorted(inline_property_names(element)))
    children = ",".join(tag_of(child) for child in element_children(element))
    return f"{tag_of(element)}|{element.get('role') or ''}|{style}|{children}"


def _name(elements: list[Tag], loop_list: str | None, name_of: dict[int, str], block_of: dict[int, str]) -> str:
    """
    A loop item is named after its list, then an explicit label or role.
    An interactive element is named by its text when every occurrence shows
    the same one, else after the component holding it; a semantic element by
    its tag. Anything else by the short copy every occurrence shows — never
    copy that varies, which is sample content — or else by the block it lives
    in and what it is (`PerspectivasCapacidadesCell`, `RadarChartMark`).
    """
    example = elements[0]
    explicit = _explicit_name(example, loop_list)
    if explicit:
        return explicit
    tag = tag_of(example)
    if tag in _INTERACTIVE:
        return _interactive_name(elements, name_of) + _NAME_BY_TAG[tag]
    if tag in _NAME_BY_TAG:
        return _NAME_BY_TAG[tag]
    texts = {_first_wordy_text(element) for element in elements}
    if len(texts) == 1 and None not in texts and len(texts_words := texts.pop().split()) <= _MAX_NAME_WORDS:
        return _pascal(" ".join(texts_words))
    context = " ".join(word for word in block_of.get(id(example), "").split() if word.lower() not in _LITTLE_WORDS)
    return _pascal(context, _MAX_CONTEXT_WORDS) + _role(example)


def _role(element: Tag) -> str:
    """What an element is, from its tag or else its shape and style."""
    tag = tag_of(element)
    if tag in _ROLE_BY_TAG:
        return _ROLE_BY_TAG[tag]
    styles = inline_styles(element)
    display = styles.get("display", "")
    if not element_children(element):
        if styles.get("border-radius") in _ROUND and not _first_wordy_text(element):
            return "Dot"
        parent = element.parent
        in_grid = isinstance(parent, Tag) and "grid" in inline_styles(parent).get("display", "")
        return "Cell" if in_grid else "Tag"
    if "grid" in display:
        return "Grid"
    if "flex" in display:
        return "Stack" if styles.get("flex-direction", "").startswith("column") else "Row"
    if any(prop in styles for prop in ("border", "box-shadow", "background", "border-radius")):
        return "Card"
    return "Group"


def _blocks_by_element(blocks_by_screen: dict[str, list[Tag]]) -> dict[int, str]:
    """
    id(element) → the name of what it lives in: the page block holding it,
    or — for a block itself, whose own name is its sample copy — the label
    of the nearest labeled element around it.
    """
    found: dict[int, str] = {}
    for blocks in blocks_by_screen.values():
        for index, block in enumerate(blocks):
            name = block_name(block, index)
            found.update({id(element): name for element in rendered_descendants(block)})
            found[id(block)] = next(
                (parent["aria-label"] for parent in block.parents
                 if isinstance(parent, Tag) and parent.get("aria-label") and INTERPOLATION not in parent["aria-label"]),
                "",
            )
    return found


def _explicit_name(example: Tag, loop_list: str | None) -> str | None:
    if loop_list:
        return _pascal(loop_list) + "Item"
    label = next(
        (v for v in (example.get("aria-label"), example.get("role")) if v and INTERPOLATION not in v), None,
    )
    return _pascal(label) if label else None


def _interactive_name(elements: list[Tag], name_of: dict[int, str]) -> str:
    texts = {_first_wordy_text(element) for element in elements}
    if len(texts) == 1 and None not in texts:
        return _pascal(texts.pop())
    return _container_name(elements[0], name_of)


def _first_wordy_text(element: Tag) -> str | None:
    return next((text for text, _ in visible_text_nodes(element) if any(c.isalpha() for c in text)), None)


def _container_name(element: Tag, name_of: dict[int, str]) -> str:
    """The component the element sits in, when one already holds it."""
    return next((name_of[id(parent)] for parent in element.parents if id(parent) in name_of), "")


def _pascal(text: str, max_words: int = 0) -> str:
    words = [w for w in re.split(r"[^\w]+", text) if w and not w.isdigit()][:max_words or _MAX_NAME_WORDS]
    return "".join(w[:1].upper() + w[1:] for w in words) or "Component"


def _unique(name: str, used: set[str]) -> str:
    candidate, n = name, 2
    while candidate in used:
        candidate, n = f"{name}{n}", n + 1
    used.add(candidate)
    return candidate


def _component(
    occurrences: list[tuple[str, Tag]], found: CanvasComponents, details: _Details, loop_list: str | None,
) -> ExtractedComponent:
    screen, example = occurrences[0]
    name = found.name_of[id(example)]
    data = details.loop_data(screen, loop_list) if loop_list else None
    return ExtractedComponent(
        name=name,
        comp_type=_TYPE_BY_ROLE.get(example.get("role") or "", _TYPE_BY_TAG.get(tag_of(example), ComponentType.COMPONENT)),
        source_code=str(example),
        source_lang=SOURCE_LANG,
        occurrence=len(occurrences),
        classes=" ".join(c for c in (example.get("class") or []) if INTERPOLATION not in c),
        styles=_styles(name, example, details.tag_rules),
        texts=_texts(name, example),
        child_refs=list(dict.fromkeys(ref for child in element_children(example) for ref in found.outermost_in(child))),
        declares_inline_styles=bool(example.get("style")),
        referenced_data={loop_list: data} if data is not None else {},
    )


def _styles(name: str, example: Tag, tag_rules: TagRules) -> list[StyleEntry]:
    styles = [StyleEntry.create(name, prop, value) for prop, value in inline_styles(example).items()]
    styles.extend(
        StyleEntry.create(f"{name} > {path}", prop, value)
        for path, element in element_paths(example)
        for prop, value in inline_styles(element).items()
    )
    for state, rules in tag_rules.get(tag_of(example), {}).items():
        if state in _STATES:
            styles.extend(StyleEntry.create(name, rule.property, rule.value, _STATES[state]) for rule in rules)
    return styles


def _texts(name: str, example: Tag) -> list[TextEntry]:
    texts = [
        TextEntry.create(text, _TEXT_TYPE_BY_TAG.get(tag, TextType.LABEL), source=name, element=tag)
        for text, tag in visible_text_nodes(example)
    ]
    for element in [example, *rendered_descendants(example)]:
        for attribute in ("title", "aria-label"):
            value = (element.get(attribute) or "").strip()
            if value and INTERPOLATION not in value:
                texts.append(TextEntry.create(value, TextType.TOOLTIP, source=name, element=tag_of(element)))
    return list({text.id: text for text in texts}.values())
