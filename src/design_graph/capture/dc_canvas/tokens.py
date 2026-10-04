"""
Design tokens of a DC canvas.

Custom properties are defined per theme selector in each page's helmet
(`.tc{--accent:…}` / `.te{--accent:…}`) and switched by an enum prop (`tema`:
claro/escuro): each selector becomes a mode named after the option that
selects it. Font families come from the pages' @font-face rules, and every
other token (sizes, weights, spacing, radii…) from the CSS-literal token
extractor the html_prototype capture already applies to stylesheets.
"""

from __future__ import annotations

import re
from collections import Counter

from design_graph.capture.dc_canvas.page import DcPage
from design_graph.capture.html_prototype.parsing.token_extractor import extract_tokens
from design_graph.capture.html_prototype.sources import RawSources, SourceFormat
from design_graph.model.entities import DesignToken, EntityId, TokenCategory

# A CSS rule: selector list and declaration block.
_RE_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_RE_CUSTOM_PROPERTY = re.compile(r"(--[\w-]+)\s*:\s*([^;]+)")
_RE_REFERENCE = re.compile(r"var\(\s*(--[\w-]+)")
_RE_FONT_FAMILY = re.compile(r"font-family\s*:\s*['\"]?([^'\";,]+)")
# `x === 'escuro' ? 'te' : 'tc'` — the logic names which option selects which class.
_RE_OPTION_SELECTS_CLASS = re.compile(r"""['"](\w+)['"]\s*\?\s*['"]([\w-]+)['"]\s*:\s*['"]([\w-]+)['"]""")
_ALL_MODES_SELECTORS = {":root", "html", "body", "*"}


def extract_canvas_tokens(pages: list[DcPage]) -> list[DesignToken]:
    texts = [page.markup for page in pages] + list(dict.fromkeys(page.styles for page in pages))
    references = Counter(name for text in texts for name in _RE_REFERENCE.findall(text))
    literal_tokens = [
        token for token in extract_tokens(RawSources(
            js="", css="\n".join(texts), inner_html="", html_hash="", format=SourceFormat.PLAIN_HTML,
        ))
        if token.category != TokenCategory.CSS_VAR
    ]
    return _custom_property_tokens(pages, references) + _font_family_tokens(pages, texts) + literal_tokens


def _custom_property_tokens(pages: list[DcPage], references: Counter) -> list[DesignToken]:
    tokens: dict[tuple[str, str], DesignToken] = {}
    for page in pages:
        definitions = _definitions_by_selector(page.styles)
        modes = _mode_of_selector(page, [s for s in definitions if s not in _ALL_MODES_SELECTORS])
        for selector, properties in definitions.items():
            mode = "" if selector in _ALL_MODES_SELECTORS else modes[selector]
            for name, value in properties.items():
                tokens.setdefault((name, mode), DesignToken(
                    id=EntityId.derive("cv", f"{name}@{mode}"), category=TokenCategory.CSS_VAR,
                    label=name, value=value, usage=references[name], mode=mode,
                ))
    return list(tokens.values())


def _definitions_by_selector(css: str) -> dict[str, dict[str, str]]:
    """Selector → the custom properties it defines, for rules that define any."""
    definitions: dict[str, dict[str, str]] = {}
    for selectors, block in _RE_RULE.findall(css):
        properties = {name: value.strip() for name, value in _RE_CUSTOM_PROPERTY.findall(block)}
        if properties:
            for selector in (s.strip() for s in selectors.split(",")):
                definitions.setdefault(selector, {}).update(properties)
    return definitions


def _mode_of_selector(page: DcPage, theme_selectors: list[str]) -> dict[str, str]:
    """
    Name each theme selector after the enum option that switches it on: as the
    page's logic states it when it does, else by matching declaration order to
    option order, else by the selector's own name.
    """
    names = {selector: selector.lstrip(".#") for selector in theme_selectors}
    options = next(
        (meta["options"] for meta in page.props.values()
         if isinstance(meta, dict) and len(meta.get("options") or []) == len(theme_selectors)),
        None,
    )
    if not options:
        return names
    by_class = _classes_named_in_logic(page.logic, options)
    if len(by_class) == len(theme_selectors):
        return {selector: by_class.get(names[selector], names[selector]) for selector in theme_selectors}
    return dict(zip(theme_selectors, options))


def _classes_named_in_logic(logic: str, options: list[str]) -> dict[str, str]:
    """Class → option, from `x === 'option' ? 'class' : 'other'` in the logic."""
    for option, chosen, other in _RE_OPTION_SELECTS_CLASS.findall(logic):
        if option in options and len(options) == 2:
            remaining = next(o for o in options if o != option)
            return {chosen: option, other: remaining}
    return {}


def _font_family_tokens(pages: list[DcPage], texts: list[str]) -> list[DesignToken]:
    families = dict.fromkeys(
        family.strip() for page in pages for family in _RE_FONT_FAMILY.findall(page.font_faces)
    )
    used = Counter(family.strip() for text in texts for family in _RE_FONT_FAMILY.findall(text))
    return [
        DesignToken(
            id=EntityId.derive("ff", family), category=TokenCategory.TYPOGRAPHY,
            label=f"font-family {family}", value=family, usage=used[family],
        )
        for family in families
    ]
