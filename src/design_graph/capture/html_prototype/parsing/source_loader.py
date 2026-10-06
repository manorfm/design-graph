"""
Decompose an HTML prototype into its raw JS, CSS, and HTML parts.

The file itself is read once by capture.base.PrototypeDocument; every
extraction and analysis module downstream receives the RawSources built here.

Supports three prototype formats (detected by format_detector):
  bundled_react — base64/gzip bundles embedded in <script> JSON
  tailwind      — plain HTML with Tailwind utility classes
  plain_html    — any other HTML
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from bs4 import BeautifulSoup

from design_graph.capture.base import PrototypeDocument
from design_graph.capture.bundler import BundleEntryError, decode_entry
from design_graph.capture.html_prototype.sources import RawSources
from design_graph.capture.resources import (
    font_resources,
    image_resources,
    is_infrastructure,
    is_script,
    script_resource,
)
from design_graph.model.entities import Resource
from design_graph.capture.html_prototype.parsing.format_detector import BUNDLED_REACT, detect

logger = logging.getLogger(__name__)

# A script tag shorter than this won't be treated as a bundled JS file
_MIN_BUNDLE_SCRIPT_LEN = 1_000


def decompose(document: PrototypeDocument) -> RawSources:
    """
    Split an already-read prototype into its raw JS, CSS and HTML parts.

    Never raises on malformed bundle JSON — logs a warning and continues.
    """
    soup = BeautifulSoup(document.text, "html.parser")
    fmt  = detect(document.text, soup)

    skipped_entries, resources = 0, []
    if fmt == BUNDLED_REACT:
        parts = _extract_bundled_react(soup)
        js, css, inner_html, skipped_entries, resources = (
            parts.js, parts.css, parts.inner_html, parts.skipped, parts.resources,
        )
    else:
        js, css, inner_html = _extract_plain(document.text, soup)

    logger.info(
        "source_loader: loaded %s | format=%s | js=%d css=%d",
        document.path.name, fmt, len(js), len(css),
    )
    if skipped_entries:
        logger.warning(
            "source_loader: %d bundle entr%s failed to decode and were dropped "
            "from %s — extraction is incomplete for the affected files",
            skipped_entries, "y" if skipped_entries == 1 else "ies", document.path.name,
        )

    return RawSources(
        js=js,
        css=css,
        inner_html=inner_html,
        html_hash=document.digest,
        format=fmt,
        skipped_entries=skipped_entries,
        resources=tuple(resources),
    )


# ── Extraction strategies ─────────────────────────────────────────────────────

@dataclass
class _BundleParts:
    js: str
    css: str
    inner_html: str
    skipped: int
    resources: list[Resource]


def _extract_bundled_react(soup: BeautifulSoup) -> _BundleParts:
    """
    Decompress a React bundle and separate what it holds: the prototype's
    own code (read as JS), its CSS and inner HTML, and everything else it
    loads — libraries, the in-browser compiler, fonts, images — described as
    resources and never read as the prototype's code.
    """
    scripts = _read_scripts(soup)
    parts = _BundleParts(
        js="", css="", inner_html=scripts.inner_html, skipped=scripts.skipped, resources=[],
    )
    js_parts, css_parts, files = list(scripts.js), [], {}
    for key, (mime, content) in scripts.entries.items():
        text = content.decode("utf-8", errors="replace")
        if "<!DOCTYPE" in text[:200]:
            parts.inner_html = text
        elif "css" in mime:
            css_parts.append(text)
        elif mime.startswith(("font/", "image/")):
            files[key] = content
        elif is_script(mime):
            resource = script_resource(key, content)
            parts.resources.append(resource)
            if not is_infrastructure(resource):
                js_parts.append(text)

    parts.inner_html = parts.inner_html or str(soup)
    # The page's own static <style> tag — the shell React hydrates into —
    # lives inside inner_html, not in a bundle entry with a "css" mime.
    # Additive: a bundle that also ships a separate CSS-mime entry keeps
    # contributing both.
    page = BeautifulSoup(parts.inner_html, "html.parser")
    css_parts += [tag.get_text() for tag in page.find_all("style") if tag.get_text().strip()]

    parts.js, parts.css = "\n".join(js_parts), "\n".join(css_parts)
    parts.resources += font_resources(parts.css, files, hints=parts.inner_html)
    parts.resources += image_resources(scripts.entries, parts.inner_html)
    return parts


@dataclass
class _Scripts:
    js: list[str]                               # plain JS blocks written straight into the page
    entries: dict[str, tuple[str, bytes]]       # bundle entries, id → (mime, bytes)
    inner_html: str
    skipped: int


def _read_scripts(soup: BeautifulSoup) -> _Scripts:
    """What the page's <script> tags hold: the bundle map's entries, an inner HTML string, plain JS."""
    scripts = _Scripts(js=[], entries={}, inner_html="", skipped=0)
    for script in soup.find_all("script"):
        text: str = script.get_text().strip()
        if len(text) > 10_000 and text.startswith("{"):  # the bundle map itself
            entries, skipped = _decompress_bundle_map(text)
            scripts.entries.update(entries)
            scripts.skipped += skipped
        elif text.startswith('"'):  # a JSON string holding the inner HTML
            scripts.inner_html = _inner_html_string(text) or scripts.inner_html
        elif len(text) > _MIN_BUNDLE_SCRIPT_LEN and not text.startswith(("[", "{")):
            scripts.js.append(text)
    return scripts


def _inner_html_string(text: str) -> str:
    try:
        content = json.loads(text)
    except json.JSONDecodeError:
        return ""
    return content if isinstance(content, str) and "<!DOCTYPE" in content else ""


def _decompress_bundle_map(text: str) -> tuple[dict[str, tuple[str, bytes]], int]:
    """Parse a bundle JSON map and decompress each entry: id → (mime, bytes)."""
    entries: dict[str, tuple[str, bytes]] = {}
    skipped = 0

    try:
        bundle = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("bundle JSON parse error (skipping script): %s", exc)
        return entries, skipped

    if isinstance(bundle, str) and "<!DOCTYPE" in bundle:
        return {"inner.html": ("text/html", bundle.encode())}, skipped
    if not isinstance(bundle, dict):
        return entries, skipped

    for key, val in bundle.items():
        if not isinstance(val, dict) or not val.get("data"):
            continue
        try:
            entries[key] = (val.get("mime", ""), decode_entry(val))
        except BundleEntryError as exc:
            skipped += 1
            logger.warning(
                "source_loader: bundle entry %r (mime=%s) failed to decode — "
                "dropped, extraction will be incomplete: %s",
                key, val.get("mime", "?"), exc,
            )
    return entries, skipped


def _extract_plain(html: str, soup: BeautifulSoup) -> tuple[str, str, str]:
    """
    Extract JS and CSS from plain HTML / Tailwind files using <script> and
    <style> tags directly.
    """
    css_parts: list[str] = []
    js_parts:  list[str] = []

    for tag in soup.find_all("style"):
        css_parts.append(tag.get_text())

    for tag in soup.find_all(style=True):
        inline = tag.get("style", "")
        if inline:
            css_parts.append(inline)

    for script in soup.find_all("script"):
        content = script.get_text().strip()
        if content:
            js_parts.append(content)

    return "\n".join(js_parts), "\n".join(css_parts), html
