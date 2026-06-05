"""
Load and decompose an HTML prototype file into its raw JS, CSS, and HTML parts.

This is the only module with file I/O in the parsing layer.
All extraction and analysis is done by other modules that receive RawSources.

Supports three prototype formats (detected by format_detector):
  bundled_react — base64/gzip bundles embedded in <script> JSON
  tailwind      — plain HTML with Tailwind utility classes
  plain_html    — any other HTML
"""

from __future__ import annotations

import asyncio
import base64
import gzip
import hashlib
import json
import logging
import sys
from pathlib import Path

from bs4 import BeautifulSoup

from design_graph.core.models import RawSources
from design_graph.parsing.format_detector import BUNDLED_REACT, detect

logger = logging.getLogger(__name__)

# A script tag shorter than this won't be treated as a bundled JS file
_MIN_BUNDLE_SCRIPT_LEN = 1_000


async def load(html_path: Path) -> RawSources:
    """
    Read an HTML prototype file and return its decomposed sources.

    Raises FileNotFoundError if html_path does not exist.
    Never raises on malformed bundle JSON — logs a warning and continues.
    """
    if not html_path.exists():
        raise FileNotFoundError(f"Prototype not found: {html_path}")

    raw_bytes = await asyncio.to_thread(html_path.read_bytes)
    html_text = raw_bytes.decode("utf-8", errors="replace")
    html_hash = hashlib.md5(raw_bytes).hexdigest()

    soup = BeautifulSoup(html_text, "html.parser")
    fmt  = detect(html_text, soup)

    if fmt == BUNDLED_REACT:
        js, css, inner_html = _extract_bundled_react(soup)
    else:
        js, css, inner_html = _extract_plain(html_text, soup)

    logger.info(
        "source_loader: loaded %s | format=%s | js=%d css=%d",
        html_path.name, fmt, len(js), len(css),
    )

    return RawSources(
        js=js,
        css=css,
        inner_html=inner_html,
        html_hash=html_hash,
        format=fmt,
    )


# ── Extraction strategies ─────────────────────────────────────────────────────

def _extract_bundled_react(soup: BeautifulSoup) -> tuple[str, str, str]:
    """
    Decompress and separate JS, CSS, and inner HTML from a React bundle.
    Bundle format: <script> containing a JSON map of {id: {data, compressed, mime}}.
    """
    js_parts:   list[str] = []
    css_parts:  list[str] = []
    inner_html = ""

    for script in soup.find_all("script"):
        text: str = script.get_text().strip()
        if not text:
            continue

        # Large JSON map — the actual bundle
        if len(text) > 10_000 and text.startswith("{"):
            js_part, css_part, html_part = _decompress_bundle_map(text)
            js_parts.extend(js_part)
            css_parts.extend(css_part)
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

    return "\n".join(js_parts), "\n".join(css_parts), inner_html


def _decompress_bundle_map(text: str) -> tuple[list[str], list[str], str]:
    """Parse a bundle JSON map and decompress each entry."""
    js_parts:  list[str] = []
    css_parts: list[str] = []
    html_part = ""

    try:
        bundle = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("bundle JSON parse error (skipping script): %s", exc)
        return js_parts, css_parts, html_part

    if isinstance(bundle, str) and "<!DOCTYPE" in bundle:
        return [], [], bundle

    if not isinstance(bundle, dict):
        return js_parts, css_parts, html_part

    for val in bundle.values():
        if not isinstance(val, dict) or not val.get("data"):
            continue
        try:
            decoded = base64.b64decode(val["data"])
            if val.get("compressed"):
                decoded = gzip.decompress(decoded)
            content = decoded.decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            logger.debug("bundle entry decompress failed: %s", exc)
            continue

        mime: str = val.get("mime", "")
        if "<!DOCTYPE" in content[:200]:
            html_part = content
        elif "css" in mime:
            css_parts.append(content)
        else:
            js_parts.append(content)

    return js_parts, css_parts, html_part


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
