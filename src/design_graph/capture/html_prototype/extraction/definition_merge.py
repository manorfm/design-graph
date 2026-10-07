"""
Same-named component definitions found at several points of one prototype's
JS, merged into one lossless component.

JS hoists `function Name(...)` declarations fully — a later declaration of the
same name replaces an earlier one, so only the last one ever runs. The merge
keeps every definition's source (labelled live or shadowed), unions what each
contributes, and takes render order from the live one.
"""

from __future__ import annotations

from design_graph.model.entities import ComponentType, ExtractedComponent


def _label_definitions(definitions: list[str]) -> str:
    """
    Every definition's source, each labelled live or shadowed — silently
    concatenating them would let an agent mistake unreachable code for the
    real implementation.
    """
    if len(definitions) <= 1:
        return definitions[0] if definitions else ""

    last = len(definitions) - 1
    labeled = [
        f"{{/* Variant {i + 1}/{len(definitions)} — "
        + ("live (last declaration wins in JS)" if i == last else "shadowed by a later declaration, never executes")
        + f" */}}\n{source}"
        for i, source in enumerate(definitions)
    ]
    return "\n\n".join(labeled)


def merge_definitions(variants: list[ExtractedComponent]) -> ExtractedComponent:
    """Merge same-named source definitions into one lossless graph entity."""
    if not variants:
        raise ValueError("component consolidation requires at least one variant")
    names = {variant.name for variant in variants}
    if len(names) != 1:
        raise ValueError("component variants must share the same name")

    definitions = list(dict.fromkeys(
        variant.source_code for variant in variants if variant.source_code
    ))
    source_code = _label_definitions(definitions)
    classes = sorted({
        class_name
        for variant in variants
        for class_name in variant.classes.split()
        if class_name
    })
    styles = {
        item.id: item for variant in variants for item in variant.styles
    }
    interactions = {
        item.id: item for variant in variants for item in variant.interactions
    }
    texts = {
        item.id: item for variant in variants for item in variant.texts
    }
    props = {
        item.id: item for variant in variants for item in variant.props
    }
    icons = {
        item.id: item for variant in variants for item in variant.icons
    }
    # Union across variants, later declarations' values winning on a
    # repeated const name — same "last declaration wins" bias
    # child_refs/source_code already apply for the live variant above.
    referenced_data: dict[str, object] = {}
    for variant in variants:
        referenced_data.update(variant.referenced_data)
    # Render order comes from the *live* variant (the last declaration —
    # same "last declaration wins in JS" criterion _label_definitions
    # already uses above to pick which source_code actually executes),
    # not a union sorted alphabetically. A variant order this component
    # only referenced in a shadowed, dead declaration is still included
    # — for completeness, matching the union semantics this dedup
    # already had — just appended after the live variant's real order
    # instead of taking equal precedence with it.
    live_variant = variants[-1]
    seen_children: set[str] = set()
    child_refs: list[str] = []
    for child in live_variant.child_refs:
        if child not in seen_children:
            seen_children.add(child)
            child_refs.append(child)
    for variant in variants:
        for child in variant.child_refs:
            if child not in seen_children:
                seen_children.add(child)
                child_refs.append(child)
    return ExtractedComponent(
        name=variants[0].name,
        comp_type=next(
            (variant.comp_type for variant in variants if variant.comp_type != ComponentType.COMPONENT),
            variants[0].comp_type,
        ),
        source_code=source_code,
        occurrence=max(variant.occurrence for variant in variants),
        classes=" ".join(classes),
        styles=list(styles.values()),
        interactions=list(interactions.values()),
        texts=list(texts.values()),
        child_refs=child_refs,
        props=list(props.values()),
        icons=list(icons.values()),
        actions=list({action.id: action for variant in variants for action in variant.actions}.values()),
        states=list({state.id: state for variant in variants for state in variant.states}.values()),
        referenced_data=referenced_data,
        source_lang=live_variant.source_lang,
        declares_inline_styles=any(variant.declares_inline_styles for variant in variants),
    )
