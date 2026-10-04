"""
Components of a DC canvas, inferred from what its pages repeat.

DC pages are written out in full — nothing names a reusable piece — so a
component is a structure the author repeated: the same element (tag, literal
style, shape of its children) on at least MIN_PAGES pages, or the item a
<sc-for> loop repeats by construction. Only elements at or below a page's
blocks qualify; the page skeleton around the blocks is layout, not a
component.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import Tag

from design_graph.capture.dc_canvas.template import (
    INTERPOLATION,
    SOURCE_LANG,
    element_children,
    inline_styles,
    rendered_descendants,
    tag_of,
    visible_text_nodes,
)
from design_graph.model.entities import (
    ComponentType,
    ExtractedComponent,
    StyleEntry,
    TextEntry,
    TextType,
)

MIN_PAGES = 3
_MIN_DESCENDANTS = 2
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
_RE_INTERPOLATION = re.compile(r"\{\{[^}]*\}\}")
_RE_LOOP_LIST = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")
_MAX_NAME_WORDS = 3


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


def infer_components(blocks_by_screen: dict[str, list[Tag]]) -> CanvasComponents:
    occurrences, loop_lists = _occurrences(blocks_by_screen)
    promoted = [
        signature for signature, found in occurrences.items()
        if signature in loop_lists or len({screen for screen, _ in found}) >= MIN_PAGES
    ]
    result = CanvasComponents(components=[])
    used: set[str] = set()
    for signature in promoted:
        elements = [element for _, element in occurrences[signature]]
        name = _unique(_name(elements, loop_lists.get(signature), result.name_of), used)
        result.name_of.update({id(element): name for element in elements})
    result.components = [
        _component(occurrences[signature][0][1], len(occurrences[signature]), result) for signature in promoted
    ]
    return result


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
    return (
        tag_of(element) in _INTERACTIVE
        or bool(element.get("role"))
        or len(rendered_descendants(element)) >= _MIN_DESCENDANTS
    )


def _loop_list(element: Tag) -> str | None:
    """The list a <sc-for> repeats this element over, when it is the loop's item."""
    parent = element.parent
    if not isinstance(parent, Tag) or parent.name != "sc-for":
        return None
    found = _RE_LOOP_LIST.search(parent.get("list") or "")
    return found.group(1).split(".")[-1] if found else "Loop"


def _signature(element: Tag) -> str:
    style = _RE_INTERPOLATION.sub("{{}}", " ".join((element.get("style") or "").lower().split()))
    children = ",".join(tag_of(child) for child in element_children(element))
    return f"{tag_of(element)}|{element.get('role') or ''}|{style}|{children}"


def _name(elements: list[Tag], loop_list: str | None, name_of: dict[int, str]) -> str:
    """
    A loop item is named after its list, then an explicit label or role.
    An interactive element is named by its text when every occurrence shows
    the same one, else after the component holding it; anything else by its
    semantic tag or the copy it shows.
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
    wordy = _first_wordy_text(example)
    return _pascal(wordy) if wordy else _pascal(tag)


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


def _pascal(text: str) -> str:
    words = [w for w in re.split(r"[^\w]+", text) if w and not w.isdigit()][:_MAX_NAME_WORDS]
    return "".join(w[:1].upper() + w[1:] for w in words) or "Component"


def _unique(name: str, used: set[str]) -> str:
    candidate, n = name, 2
    while candidate in used:
        candidate, n = f"{name}{n}", n + 1
    used.add(candidate)
    return candidate


def _component(example: Tag, occurrence: int, found: CanvasComponents) -> ExtractedComponent:
    name = found.name_of[id(example)]
    return ExtractedComponent(
        name=name,
        comp_type=_TYPE_BY_ROLE.get(example.get("role") or "", _TYPE_BY_TAG.get(tag_of(example), ComponentType.COMPONENT)),
        source_code=str(example),
        source_lang=SOURCE_LANG,
        occurrence=occurrence,
        classes=" ".join(c for c in (example.get("class") or []) if INTERPOLATION not in c),
        styles=[StyleEntry.create(name, prop, value) for prop, value in inline_styles(example).items()],
        texts=_texts(name, example),
        child_refs=list(dict.fromkeys(ref for child in element_children(example) for ref in found.outermost_in(child))),
        declares_inline_styles=bool(example.get("style")),
    )


def _texts(name: str, example: Tag) -> list[TextEntry]:
    texts = [
        TextEntry.create(text, _TEXT_TYPE_BY_TAG.get(tag, TextType.LABEL), source=name, element=tag)
        for text, tag in visible_text_nodes(example)
    ]
    for element in [example, *rendered_descendants(example)]:
        for attribute in ("title", "aria-label"):
            value = (element.get(attribute) or "").strip()
            if value and INTERPOLATION not in value and TextEntry.is_plausible_content(value):
                texts.append(TextEntry.create(value, TextType.TOOLTIP, source=name, element=tag_of(element)))
    return list({text.id: text for text in texts}.values())
