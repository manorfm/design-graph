"""
Capture for single-document HTML prototypes: bundled React apps (Claude
Artifacts, Cursor Composer), Tailwind pages and plain HTML.

Two extraction strategies share one loader: documents that declare React
component functions are read through their JS function boundaries; plain
documents without them are read as repeating DOM patterns.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from dataclasses import dataclass, replace

from bs4 import BeautifulSoup

from design_graph.capture.base import CaptureResult, ComponentProgress, PrototypeDocument
from design_graph.model.entities import (
    ExtractedComponent,
    ExtractedScreen,
    ExtractedSection,
    IconAsset,
    resolve_icon_markers,
)
from design_graph.capture.html_prototype.sources import FunctionBoundary, RawSources
from design_graph.capture.html_prototype.patterns import RE_COMP_FN
from design_graph.capture.html_prototype.extraction.alias_extractor import apply_aliases, extract_component_aliases
from design_graph.capture.html_prototype.extraction.component_extractor import (
    extract_all_components,
    extract_component,
    select_renderable_boundaries,
)
from design_graph.capture.html_prototype.extraction.module_text_extractor import extract_module_level_texts
from design_graph.capture.html_prototype.extraction.plain_html_component_extractor import dom_patterns_to_extracted_components
from design_graph.capture.html_prototype.extraction.screen_extractor import extract_screens, is_screen
from design_graph.capture.html_prototype.extraction.jsx_sanitizer import was_simplified
from design_graph.capture.html_prototype.extraction.section_extractor import extract_sections, extract_sections_for_plain_html
from design_graph.capture.html_prototype.parsing.css_class_resolver import (
    extract_css_rules,
    extract_responsive_css_rules,
    extract_tag_pseudo_rules,
)
from design_graph.capture.html_prototype.parsing.format_detector import PLAIN_HTML
from design_graph.capture.html_prototype.parsing.html_parser import extract_dom_patterns
from design_graph.capture.html_prototype.parsing.js_parser import find_all_boundaries, find_module_level_constants
from design_graph.capture.html_prototype.parsing.palette_extractor import discover_prototype_palette
from design_graph.capture.html_prototype.parsing.source_loader import decompose
from design_graph.capture.html_prototype.parsing.token_extractor import extract_tokens

logger = logging.getLogger(__name__)

CAPTURE_NAME = "html_prototype"

# Any real HTML document carries at least one of these document-level tags.
_RE_HTML_DOCUMENT = re.compile(r"<(?:!doctype\s+html|html|head|body)\b", re.IGNORECASE)


class HtmlPrototypeCapture:
    """Reads any HTML document — the fallback capture for single-file prototypes."""

    name = CAPTURE_NAME

    def recognizes(self, document: PrototypeDocument) -> bool:
        return bool(_RE_HTML_DOCUMENT.search(document.text))

    async def capture(
        self,
        document: PrototypeDocument,
        *,
        concurrency: int,
        on_component_extracted: ComponentProgress | None = None,
    ) -> CaptureResult:
        sources = await asyncio.to_thread(decompose, document)
        if sources.format == PLAIN_HTML and not has_react_functions(sources.js):
            return await extract_plain_html(sources)
        return await extract_react(sources, concurrency, on_component_extracted)


    def capture_fragment(self, source: str) -> ExtractedComponent | None:
        """
        Read a bare JSX expression as a component, with the same extractor a
        whole bundle goes through — wrapped in a synthetic function so its
        boundary can be found.

        No stylesheet, palette or module constants exist for a standalone
        fragment, so class-resolved styles and spread references resolve to
        nothing here; inline styles, child references and texts are read
        exactly as in a build.
        """
        if not source.strip():
            return None
        js = f"function {_FRAGMENT_WRAPPER_NAME}() {{\n  return (\n{source}\n  );\n}}"
        boundaries = find_all_boundaries(js)
        if not boundaries:
            return None
        return extract_component(js, boundaries[0], 1)


# A fragment is wrapped in a function of this name to be read. Plain PascalCase
# with no leading underscore — find_all_boundaries only recognizes names that
# follow the convention real component names use.
_FRAGMENT_WRAPPER_NAME = "DesignGraphFragment"


def has_react_functions(js: str) -> bool:
    """True when the JS declares at least one PascalCase (component) function."""
    return bool(RE_COMP_FN.search(js))


async def extract_react(
    sources: RawSources,
    concurrency: int,
    on_component_extracted: ComponentProgress | None = None,
) -> CaptureResult:
    """
    Read a prototype through its JS function boundaries (bundled React,
    Tailwind, or plain HTML with inline React).

    A screen boundary is never also extracted as a component — screens and
    components are disjoint by construction.

    on_component_extracted: forwarded to extract_all_components so the caller
        can display per-component extraction progress.
    """
    tokens_task     = asyncio.create_task(asyncio.to_thread(extract_tokens, sources))
    boundaries_task = asyncio.create_task(asyncio.to_thread(find_all_boundaries, sources.js))
    tokens, all_boundaries = await asyncio.gather(tokens_task, boundaries_task)

    # UI copy from shared module-level constant arrays (const DETAIL_TABS =
    # [...]) — outside every function boundary by construction, so it's the
    # one text source component/section extraction can never see.
    module_texts = extract_module_level_texts(sources.js, all_boundaries)

    # The prototype's own color palette (const C = { bg: '#404040', ... }),
    # if it has one — lets a style value written as a direct reference
    # (`background: C.bg`) fold to its literal hex at extraction time, so
    # it links to a Token exactly like a literal color would.
    palette = discover_prototype_palette(sources.js)

    # Every module-level `const NAME = {...}`/`[...]` in the whole file —
    # a component whose own body references one by name (e.g. an
    # icon-name -> SVG-path lookup table indexed as `ICONS[name]`) gets its
    # literal content attached verbatim (see module_data_extractor.py,
    # docs/changes/C39).
    module_constants = find_module_level_constants(sources.js, all_boundaries)

    rule_map      = extract_css_rules(sources.css) if sources.css else {}
    tag_rule_map  = extract_tag_pseudo_rules(sources.css) if sources.css else {}
    responsive_rule_map = extract_responsive_css_rules(sources.css) if sources.css else {}
    screen_bounds, comp_bounds = _split_screens_from_components(sources.js, all_boundaries)
    occurrences   = Counter(b.name for b in all_boundaries)

    logger.info(
        "html_prototype: resolved %d CSS class rules, %d tag pseudo-class rules, "
        "%d responsive (@media) class rules from stylesheet",
        len(rule_map), len(tag_rule_map), len(responsive_rule_map),
    )

    extracted_comps = await extract_all_components(
        sources.js, comp_bounds, occurrences,
        concurrency=concurrency, rule_map=rule_map, tag_rule_map=tag_rule_map,
        responsive_rule_map=responsive_rule_map,
        palette=palette, module_constants=module_constants,
        on_component_extracted=on_component_extracted,
    )

    screens = extract_screens(sources.js, all_boundaries)
    sections_map = await _extract_sections_by_screen(
        sources.js, screens, {b.name: b for b in screen_bounds}, rule_map, concurrency,
    )

    aliases = extract_component_aliases(sources.js, {comp.name for comp in extracted_comps})
    if aliases:
        logger.info("html_prototype: resolved %d component aliases: %s", len(aliases), aliases)
        extracted_comps, screens, sections_map = _resolve_aliases(
            aliases, extracted_comps, screens, sections_map,
        )

    return _described(CaptureResult(
        capture=CAPTURE_NAME,
        components=extracted_comps,
        screens=screens,
        sections=sections_map,
        tokens=tokens,
        module_texts=module_texts,
        skipped_entries=sources.skipped_entries,
    ), _JSX)


def _split_screens_from_components(
    js: str, boundaries: list[FunctionBoundary],
) -> tuple[list[FunctionBoundary], list[FunctionBoundary]]:
    """Renderable boundaries split into (screens, components) — disjoint by construction."""
    screens: list[FunctionBoundary] = []
    components: list[FunctionBoundary] = []
    for boundary in select_renderable_boundaries(js, boundaries):
        target = screens if is_screen(boundary.name, js[boundary.start:boundary.end]) else components
        target.append(boundary)
    return screens, components


async def _extract_sections_by_screen(
    js: str,
    screens: list[ExtractedScreen],
    screen_bounds: dict[str, FunctionBoundary],
    rule_map: dict,
    concurrency: int,
) -> dict[str, list[ExtractedSection]]:
    """Sections of every screen, one worker per screen; a screen with no boundary has none."""
    sem = asyncio.Semaphore(concurrency)

    async def _sections_of(screen: ExtractedScreen) -> tuple[str, list[ExtractedSection]]:
        boundary = screen_bounds.get(screen.name)
        if not boundary:
            return screen.name, []
        async with sem:
            return screen.name, await asyncio.to_thread(extract_sections, js, screen, boundary, rule_map)

    return dict(await asyncio.gather(*[_sections_of(screen) for screen in screens]))


def _resolve_aliases(
    aliases: dict[str, str],
    components: list[ExtractedComponent],
    screens: list[ExtractedScreen],
    sections_map: dict[str, list[ExtractedSection]],
) -> tuple[list[ExtractedComponent], list[ExtractedScreen], dict[str, list[ExtractedSection]]]:
    """
    Point every reference to a re-exported alias (`const Badge = window.V6K.Pill`)
    at its real definition — in components, screens and sections alike.
    """
    components = [replace(c, child_refs=apply_aliases(c.child_refs, aliases)) for c in components]
    screens = [replace(s, component_refs=apply_aliases(s.component_refs, aliases)) for s in screens]
    sections_map = {
        screen_name: [replace(sec, component_refs=apply_aliases(sec.component_refs, aliases)) for sec in sections]
        for screen_name, sections in sections_map.items()
    }
    return components, screens, sections_map


async def extract_plain_html(sources: RawSources) -> CaptureResult:
    """
    Read a plain HTML document: repeating DOM patterns become components,
    HTML5 semantic elements become sections, and the whole document is one
    synthetic screen.
    """
    tokens = await asyncio.to_thread(extract_tokens, sources)
    soup   = await asyncio.to_thread(BeautifulSoup, sources.inner_html, "html.parser")

    patterns        = await asyncio.to_thread(extract_dom_patterns, soup)
    extracted_comps = dom_patterns_to_extracted_components(patterns)

    screen_name = _document_screen_name(soup)
    screen      = ExtractedScreen(
        name=screen_name,
        component_refs=[c.name for c in extracted_comps],
        sections_count=0,
    )
    sections = await asyncio.to_thread(extract_sections_for_plain_html, soup, screen_name)

    logger.info(
        "html_prototype: %d DOM patterns → %d components, %d semantic sections",
        len(patterns), len(extracted_comps), len(sections),
    )
    return _described(CaptureResult(
        capture=CAPTURE_NAME,
        components=extracted_comps,
        screens=[screen],
        sections={screen_name: sections},
        tokens=tokens,
        skipped_entries=sources.skipped_entries,
    ), _HTML)


@dataclass(frozen=True)
class _SourceLanguage:
    """How this capture's stored sources are written, and how to read facts off them."""

    name: str
    inline_style_attribute: str  # what declares inline styling in this language
    simplifies: bool             # whether the stored source went through sanitize_jsx


_JSX  = _SourceLanguage(name="jsx", inline_style_attribute="style={", simplifies=True)
_HTML = _SourceLanguage(name="html", inline_style_attribute='style="', simplifies=False)


def _described(result: CaptureResult, language: _SourceLanguage) -> CaptureResult:
    """State, on every captured source, its language and what storing it changed."""
    def simplified(source: str) -> bool:
        return language.simplifies and was_simplified(source)

    result.components = [
        replace(
            comp,
            source_lang=language.name,
            source_simplified=simplified(comp.source_code),
            declares_inline_styles=language.inline_style_attribute in _with_icons(comp.source_code, comp.icons),
        )
        for comp in result.components
    ]
    result.screens = [
        replace(screen, source_lang=language.name, source_simplified=simplified(screen.source_code))
        for screen in result.screens
    ]
    result.sections = {
        screen_name: [replace(section, source_lang=language.name) for section in sections]
        for screen_name, sections in result.sections.items()
    }
    return result


def _with_icons(source: str, icons: list[IconAsset]) -> str:
    """The source as rendered: icon markers expanded back into their markup."""
    return resolve_icon_markers(source, {icon.id: icon.markup for icon in icons})


def _document_screen_name(soup: BeautifulSoup) -> str:
    """PascalCase screen name from the document <title> ("My App Title" → "MyAppTitlePage")."""
    title = soup.find("title")
    if title:
        words = [w.capitalize() for w in title.get_text(strip=True).split() if w.isalnum()]
        if words:
            name = "".join(words[:3])
            return name if name.endswith(("Page", "Screen")) else name + "Page"
    return "MainPage"
