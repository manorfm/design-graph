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
from typing import Callable, Iterable

from bs4 import Tag

from design_graph.capture.dc_canvas.instances import representative
from design_graph.capture.dc_canvas.logic import selection_branches
from design_graph.capture.dc_canvas.traits import main_content, shared_traits
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
from design_graph.capture.actions import effect_of, trigger_of
from design_graph.capture.base import ComponentProgress
from design_graph.model.entities import (
    Action,
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
_RE_MEMBER = re.compile(r"\{\{\s*(?:[\w$]+\.)*([\w$]+)\s*\}\}")
_RE_ITEM = re.compile(r"\{\{\s*([\w$]+)\.")
_MAX_NAME_WORDS = 3
_MAX_CONTEXT_WORDS = 2
_MAX_TRAITS = 2
# Roles that only arrange other elements: named by what they hold when nothing else tells them apart.
_CONTAINER_ROLES = {"Stack", "Row", "Grid", "Group", "Card"}
# Articles, prepositions and conjunctions carry no meaning in a name ("Convites e participação" → ConvitesParticipação).
_LITTLE_WORDS = frozenset(
    "a o as os um uma de da do das dos e ou em no na nos nas por para com que se the of and or to in on for".split()
)
_ROUND = {"50%", "999px", "9999px", "100%"}
_SVG_MARKS = ("path", "line", "polyline", "polygon", "rect", "circle", "ellipse", "text")
_ROLE_BY_TAG = {
    "td": "Cell", "th": "Cell", "tr": "Row", "li": "Item", "ul": "List", "ol": "List", "img": "Image",
    "p": "Text", "label": "Label", "svg": "Chart", **{f"h{n}": "Heading" for n in range(1, 7)},
    "legend": "Legend", "fieldset": "Fieldset", "figure": "Figure", "figcaption": "Caption",
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
HandlerOf = Callable[[str, str], "str | None"]    # (screen, member name) → the handler its logic gives it, or None


def infer_components(
    blocks_by_screen: dict[str, list[Tag]],
    tag_rules: TagRules | None = None,
    loop_data: LoopData | None = None,
    handler_of: HandlerOf | None = None,
    on_component: ComponentProgress | None = None,
) -> CanvasComponents:
    """
    tag_rules: pseudo-class rules the pages' styles declare for a bare tag
        (`a:hover`), applied to every component rendered as that tag.
    loop_data: where a loop item's list is looked up, to attach its values.
    on_component: told (name, index, total) as each component is extracted.
    """
    occurrences, loop_lists = _occurrences(blocks_by_screen)
    promoted = [signature for signature in occurrences if _is_repeated(signature, occurrences, loop_lists)]
    result = CanvasComponents(components=[])
    _name_promoted(promoted, occurrences, result.name_of, _blocks_by_element(blocks_by_screen))
    details = _Details(tag_rules or {}, loop_data or _no_loop_data, handler_of or _no_handler)
    report = on_component or _no_progress
    for index, signature in enumerate(promoted, start=1):
        result.components.append(_component(occurrences[signature], result, details, loop_lists.get(signature)))
        report(result.components[-1].name, index, len(promoted))
    return result


def _name_promoted(
    promoted: list[str], occurrences: dict[str, list[tuple[str, Tag]]], name_of: dict[int, str], block_of: dict[int, str],
) -> None:
    """Give each promoted structure a unique name, recorded for every element showing it."""
    used: set[str] = set()
    for signature in promoted:
        elements = [element for _, element in occurrences[signature]]
        name = _unique(_name(elements, name_of, block_of), used)
        name_of.update({id(element): name for element in elements})


@dataclass(frozen=True)
class _Details:
    tag_rules: TagRules
    loop_data: LoopData
    handler_of: HandlerOf


def fragment_component(root: Tag) -> ExtractedComponent:
    """A standalone fragment read as one component, outside any canvas."""
    found = CanvasComponents(components=[], name_of={id(root): "Fragment"})
    return _component([("", root)], found, _Details({}, _no_loop_data, _no_handler), None)


def _no_progress(name: str, index: int, total: int) -> None:
    return None


def _no_loop_data(screen: str, name: str) -> None:
    return None


def _no_handler(screen: str, key: str) -> None:
    return None


def element_actions(
    owner: str, elements: list[tuple[str, Tag]], handler_of: Callable[[str, str], "str | None"] | None = None,
) -> list[Action]:
    """
    Each event attribute (`sc-camel-on-click="{{o.pick}}"`) on `elements`
    (path, element), once per element. With `handler_of` (list repeating the
    element, member name) the handler is what the page's logic gives that
    member; without it, or when the logic says nothing, the binding as the
    template writes it.
    """
    actions: dict[str, Action] = {}
    for path, element in elements:
        for attribute, value in element.attrs.items():
            if not (attribute.startswith("sc-") and "on-" in attribute):
                continue
            key = _RE_MEMBER.search(value)
            handler = (handler_of(_repeating_list(element, value), key.group(1)) if handler_of and key else None) or value
            action = Action.create(owner, trigger_of(attribute), path, handler, effect_of(handler))
            actions.setdefault(action.id, action)
    return list(actions.values())


def _repeating_list(element: Tag, binding: str) -> str:
    """The list whose loop names the binding's item (`{{o.pick}}` inside `<sc-for list="{{sen}}" as="o">` → sen)."""
    item = _RE_ITEM.search(binding)
    loop = next((parent for parent in element.parents
                 if item and parent.name == "sc-for" and parent.get("as") == item.group(1)), None)
    found = _RE_LOOP_LIST.search(loop.get("list") or "") if loop else None
    return found.group(1) if found else ""


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


def _name(elements: list[Tag], name_of: dict[int, str], block_of: dict[int, str]) -> str:
    """
    A loop item is named after its list, then an explicit label or role.
    An interactive element is named by its text, else after the component
    holding it; a semantic element by its tag. Anything else by its short
    copy — never copy that varies, which is sample content — or else by the
    block it lives in and what it is (`PerspectivasCapacidadesCell`).
    Every one of these must be shared by all the occurrences: a list, label,
    container or block only one of them has would name the component after
    one screen, so the name falls back to what it is, told apart by what it
    looks like everywhere (`CapsBoldTag`, `SerifLargeHeading`) or, for a
    container, by what it holds (`HeadingStack`).
    """
    explicit = _explicit_name(elements)
    if explicit:
        return explicit
    example = elements[0]
    tag = tag_of(example)
    if tag in _INTERACTIVE:
        return _interactive_name(elements, name_of) + _NAME_BY_TAG[tag]
    if tag in _NAME_BY_TAG:
        return _NAME_BY_TAG[tag]
    copy = _short_shared_copy(elements)
    if copy:
        return _pascal(copy)
    return _qualifier(elements, block_of) + _role(example)


def _qualifier(elements: list[Tag], block_of: dict[int, str]) -> str:
    """
    What goes before the role: the block every occurrence lives in, else up
    to two traits they all show, else — for a container — what it holds.
    """
    block = _shared(block_of.get(id(element), "") for element in elements) or ""
    context = " ".join(word for word in block.split() if word.lower() not in _LITTLE_WORDS)
    if context:
        return _pascal(context, _MAX_CONTEXT_WORDS)
    looks = "".join(shared_traits(elements)[:_MAX_TRAITS])
    if looks or _role(elements[0]) not in _CONTAINER_ROLES:
        return looks
    return main_content(elements[0])


def _short_shared_copy(elements: list[Tag]) -> str | None:
    """The copy every occurrence shows, when it is short enough to be a name."""
    copy = _shared(_first_wordy_text(element) for element in elements)
    return copy if copy and len(copy.split()) <= _MAX_NAME_WORDS else None


def _shared(values: Iterable[str | None]) -> str | None:
    """The one value every occurrence gives, or None when they differ or give none."""
    found = set(values)
    return found.pop() if len(found) == 1 else None


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


def _explicit_name(elements: list[Tag]) -> str | None:
    loop_list = _shared(_loop_list(element) for element in elements)
    if loop_list:
        return _pascal(loop_list) + "Item"
    for attribute in ("aria-label", "role"):
        label = _shared(_literal_attribute(element, attribute) for element in elements)
        if label:
            return _pascal(label)
    return None


def _literal_attribute(element: Tag, attribute: str) -> str | None:
    """The attribute's value when the template writes it out, not when it interpolates one."""
    value = element.get(attribute)
    return value if value and INTERPOLATION not in value else None


def _interactive_name(elements: list[Tag], name_of: dict[int, str]) -> str:
    text = _shared(_first_wordy_text(element) for element in elements)
    if text:
        return _pascal(text)
    return _shared(_container_name(element, name_of) for element in elements) or ""


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
    screen, example = _representative_occurrence(occurrences)
    name = found.name_of[id(example)]
    return ExtractedComponent(
        name=name,
        comp_type=_TYPE_BY_ROLE.get(example.get("role") or "", _TYPE_BY_TAG.get(tag_of(example), ComponentType.COMPONENT)),
        source_code=str(example),
        source_lang=SOURCE_LANG,
        occurrence=len(occurrences),
        classes=" ".join(c for c in (example.get("class") or []) if INTERPOLATION not in c),
        styles=_styles(name, example, details.tag_rules)
        + _selection_styles(name, example, lambda key: details.handler_of(screen, key)),
        texts=_texts(name, example),
        actions=element_actions(name, [
            (tag_of(example), example), *((f"{tag_of(example)} > {path}", e) for path, e in element_paths(example)),
        ]),
        child_refs=list(dict.fromkeys(ref for child in element_children(example) for ref in found.outermost_in(child))),
        declares_inline_styles=bool(example.get("style")),
        referenced_data=_referenced_data(occurrences, details.loop_data) if loop_list else {},
    )


def _representative_occurrence(occurrences: list[tuple[str, Tag]]) -> tuple[str, Tag]:
    """(screen, element) of the occurrence the component is described by."""
    example = representative([element for _, element in occurrences])
    return next((screen, element) for screen, element in occurrences if element is example)


def _referenced_data(occurrences: list[tuple[str, Tag]], loop_data: LoopData) -> dict[str, object]:
    """
    The literal value of every list the item is repeated by, read on the
    screen of each occurrence, once each. A list named alike on another screen
    with other values is kept apart under `name · screen`, never dropped.
    """
    found: dict[str, object] = {}
    for screen, element in occurrences:
        list_name = _loop_list(element)
        value = loop_data(screen, list_name) if list_name else None
        if value is None:
            continue
        key = list_name if found.get(list_name, value) == value else f"{list_name} · {screen}"
        found.setdefault(key, value)
    return found


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


def _selection_styles(name: str, example: Tag, member_of: Callable[[str], "str | None"]) -> list[StyleEntry]:
    """
    A declaration whose value the page's logic picks by selection — `border:
    1px solid {{o.bc}}` with `bc: sel === o.id ? 'var(--accent)' : 'var(--rule)'`
    — as the component's default style and its selected one.
    """
    styles: list[StyleEntry] = []
    for path, element in [("", example), *element_paths(example)]:
        owner = f"{name} > {path}" if path else name
        for declaration in (element.get("style") or "").split(";"):
            prop, _, value = (part.strip() for part in declaration.partition(":"))
            key = _RE_MEMBER.search(value)
            expression = member_of(key.group(1)) if key else None
            branches = selection_branches(expression) if expression else None
            if branches:
                chosen, other = (value.replace(key.group(0), branch) for branch in branches)
                styles += [StyleEntry.create(owner, prop.lower(), other),
                           StyleEntry.create(owner, prop.lower(), chosen, StyleState.SELECTED)]
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
