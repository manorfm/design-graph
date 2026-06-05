"""
Detects the format of an HTML prototype file.

Three formats are supported:
  bundled_react — React app bundled into a single HTML (with base64/gzip scripts)
  tailwind      — HTML using Tailwind CSS utility classes
  plain_html    — Any other HTML document

Detection is best-effort. When uncertain, falls back to plain_html.
Never raises exceptions — invalid HTML is treated as plain_html.
"""

from __future__ import annotations

import logging

from bs4 import BeautifulSoup

from design_graph.core.patterns import RE_COMPRESSED_BUNDLE, RE_TAILWIND_CLASS

logger = logging.getLogger(__name__)

# ── Format name constants ─────────────────────────────────────────────────────

BUNDLED_REACT = "bundled_react"
TAILWIND      = "tailwind"
PLAIN_HTML    = "plain_html"

# A script this large that contains createElement is almost certainly a React bundle
_REACT_BUNDLE_SCRIPT_MIN_LEN = 100_000


def detect(html: str, soup: BeautifulSoup) -> str:
    """
    Inspect the HTML and return the prototype format.

    Checks in priority order:
    1. bundled_react  — compressed bundle flag OR oversized createElement script
    2. tailwind       — Tailwind utility classes in <style> tags
    3. plain_html     — default fallback
    """
    try:
        for script in soup.find_all("script"):
            text: str = script.get_text()

            if RE_COMPRESSED_BUNDLE.search(text):
                logger.debug("format=bundled_react (compressed bundle flag)")
                return BUNDLED_REACT

            if len(text) > _REACT_BUNDLE_SCRIPT_MIN_LEN and "createElement" in text:
                logger.debug("format=bundled_react (large createElement script)")
                return BUNDLED_REACT

        style_text = " ".join(tag.get_text() for tag in soup.find_all("style"))
        if RE_TAILWIND_CLASS.search(style_text):
            logger.debug("format=tailwind")
            return TAILWIND

    except Exception as exc:  # noqa: BLE001
        logger.warning("format detection error — falling back to plain_html: %s", exc)

    logger.debug("format=plain_html (default)")
    return PLAIN_HTML
