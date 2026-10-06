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
from design_graph.capture.resources import font_resources, image_resource, is_infrastructure, script_resource
from design_graph.model.entities import Resource
from design_graph.capture.html_prototype.parsing.format_detector import BUNDLED_REACT, detect

logger = logging.getLogger(__name__)

# Bundle entries read as code; any other kind of file is never read as the prototype's code.
_SCRIPT_MIMES = ("javascript", "ecmascript", "jsx", "typescript", "babel")

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
    js_parts:   list[str] = []
    css_parts:  list[str] = []
    entries:    dict[str, tuple[str, bytes]] = {}
    inner_html = ""
    skipped = 0

    for script in soup.find_all("script"):
        text: str = script.get_text().strip()
        if not text:
            continue

        # Large JSON map — the actual bundle
        if len(text) > 10_000 and text.startswith("{"):
            bundle_entries, entry_skipped = _decompress_bundle_map(text)
            entries.update(bundle_entries)
            skipped += entry_skipped
            continue

        # Short JSON string containing inner HTML
        if text.startswith('"'):
            try:
                content = json.loads(text)
                if isinstance(content, str) and "<!DOCTYPE" in content:
                    inner_html = content
            except json.JSONDecodeError:
                pass
            continue

        # Plain JS block
        if len(text) > _MIN_BUNDLE_SCRIPT_LEN and not text.startswith(("[", "{")):
            js_parts.append(text)

    resources: list[Resource] = []
    files: dict[str, bytes] = {}
    for key, (mime, content) in entries.items():
        text = content.decode("utf-8", errors="replace")
        if "<!DOCTYPE" in text[:200]:
            inner_html = text
        elif "css" in mime:
            css_parts.append(text)
        elif mime.startswith(("font/", "image/")):
            files[key] = content
        elif any(kind in mime for kind in _SCRIPT_MIMES):
            resource = script_resource(key, content)
            resources.append(resource)
            if not is_infrastructure(resource):
                js_parts.append(text)

    if not inner_html:
        inner_html = str(soup)

    # The page's own static <style> tag — the shell React hydrates into —
    # lives inside inner_html, not in a bundle entry with a "css" mime.
    # Additive: a bundle that also ships a separate CSS-mime entry keeps
    # contributing both.
    page = BeautifulSoup(inner_html, "html.parser")
    for style_tag in page.find_all("style"):
        style_text = style_tag.get_text()
        if style_text.strip():
            css_parts.append(style_text)

    css = "\n".join(css_parts)
    resources += font_resources(css, files, hints=inner_html)
    resources += _image_resources(page, entries)
    return _BundleParts("\n".join(js_parts), css, inner_html, skipped, resources)


def _image_resources(page: BeautifulSoup, entries: dict[str, tuple[str, bytes]]) -> list[Resource]:
    """Every embedded image, named by the role the page gives it (`<link rel="icon">` → favicon)."""
    roles = {
        link.get("href"): "favicon"
        for link in page.find_all("link", href=True)
        if "icon" in " ".join(link.get("rel") or [])
    }
    return [
        image_resource(key, content, mime, roles.get(key, ""))
        for key, (mime, content) in entries.items() if mime.startswith("image/")
    ]


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
