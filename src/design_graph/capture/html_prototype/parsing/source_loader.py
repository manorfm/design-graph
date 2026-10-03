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

import base64
import gzip
import json
import logging

from bs4 import BeautifulSoup

from design_graph.capture.base import PrototypeDocument
from design_graph.capture.html_prototype.sources import RawSources
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

    skipped_entries = 0
    if fmt == BUNDLED_REACT:
        js, css, inner_html, skipped_entries = _extract_bundled_react(soup)
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
    )


# ── Extraction strategies ─────────────────────────────────────────────────────

def _extract_bundled_react(soup: BeautifulSoup) -> tuple[str, str, str, int]:
    """
    Decompress and separate JS, CSS, and inner HTML from a React bundle.
    Bundle format: <script> containing a JSON map of {id: {data, compressed, mime}}.
    """
    js_parts:   list[str] = []
    css_parts:  list[str] = []
    inner_html = ""
    skipped = 0

    for script in soup.find_all("script"):
        text: str = script.get_text().strip()
        if not text:
            continue

        # Large JSON map — the actual bundle
        if len(text) > 10_000 and text.startswith("{"):
            js_part, css_part, html_part, entry_skipped = _decompress_bundle_map(text)
            js_parts.extend(js_part)
            css_parts.extend(css_part)
            skipped += entry_skipped
            if html_part:
                inner_html = html_part
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

    if not inner_html:
        inner_html = str(soup)

    # The page's own static <style> tag — the shell React hydrates into —
    # lives inside inner_html, not in a bundle entry with a "css" mime.
    # Additive: a bundle that also ships a separate CSS-mime entry keeps
    # contributing both.
    for style_tag in BeautifulSoup(inner_html, "html.parser").find_all("style"):
        style_text = style_tag.get_text()
        if style_text.strip():
            css_parts.append(style_text)

    return "\n".join(js_parts), "\n".join(css_parts), inner_html, skipped


def _decompress_bundle_map(text: str) -> tuple[list[str], list[str], str, int]:
    """Parse a bundle JSON map and decompress each entry."""
    js_parts:  list[str] = []
    css_parts: list[str] = []
    html_part = ""
    skipped = 0

    try:
        bundle = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("bundle JSON parse error (skipping script): %s", exc)
        return js_parts, css_parts, html_part, skipped

    if isinstance(bundle, str) and "<!DOCTYPE" in bundle:
        return [], [], bundle, skipped

    if not isinstance(bundle, dict):
        return js_parts, css_parts, html_part, skipped

    for key, val in bundle.items():
        if not isinstance(val, dict) or not val.get("data"):
            continue
        try:
            decoded = base64.b64decode(val["data"])
            if val.get("compressed"):
                decoded = gzip.decompress(decoded)
            content = decoded.decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            skipped += 1
            logger.warning(
                "source_loader: bundle entry %r (mime=%s) failed to decode — "
                "dropped, extraction will be incomplete: %s",
                key, val.get("mime", "?"), exc,
            )
            continue

        mime: str = val.get("mime", "")
        if "<!DOCTYPE" in content[:200]:
            html_part = content
        elif "css" in mime:
            css_parts.append(content)
        else:
            js_parts.append(content)

    return js_parts, css_parts, html_part, skipped


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
