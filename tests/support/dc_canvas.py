"""
Builds synthetic DC canvas prototypes for tests — the same two bundler
layers a real canvas export has, around page templates the test writes.

A canvas is an outer bundle whose template lays out boards (one iframe per
page) and whose manifest holds each page as a gzip+base64 HTML entry; every
page is itself a bundle whose template is the DC page (<x-dc> + logic script)
and whose manifest holds the runtime, React and font files.
"""

from __future__ import annotations

import base64
import gzip
import html
import json
import uuid
from dataclasses import dataclass, field

RUNTIME_JS = "// GENERATED from dc-runtime/src/*.ts - do not edit.\n(()=>{})();"
FONT_BYTES = b"wOF2-fake-font"


@dataclass
class Page:
    """One board: its canvas title and size, and the DC page shown in it."""

    title: str
    body: str                       # markup inside <x-dc>, after the helmet
    width: int = 390
    height: int = 844
    helmet_css: str = ""
    logic: str = "class Component extends DCLogic {\n  renderVals() {\n    return {};\n  }\n}"
    props: dict = field(default_factory=lambda: {"tema": {"editor": "enum", "options": ["claro", "escuro"],
                                                          "default": "claro"}})
    font_family: str = "IBM Plex Sans"
    is_dc: bool = True              # False writes an ordinary page instead of a DC one


def _entry(content: bytes, mime: str) -> dict:
    return {"mime": mime, "compressed": True, "data": base64.b64encode(gzip.compress(content)).decode()}


def _script_safe(json_text: str) -> str:
    """JSON that can sit inside a <script> element — the bundler escapes every "</"."""
    return json_text.replace("</", "<\\u002F")


def _bundle(title: str, template: str, manifest: dict, ext_resources: list | None = None,
            page_order: list | None = None) -> str:
    return (
        "<!DOCTYPE html>\n<html>\n<head>\n  <meta charset=\"utf-8\">\n"
        f"  <title>{html.escape(title)}</title>\n</head>\n<body>\n"
        f"  <div id=\"__bundler_placeholder\">Loading {html.escape(title)}...</div>\n"
        "  <script>\ndocument.addEventListener('DOMContentLoaded', async function() {});\n  </script>\n\n"
        f"  <script type=\"__bundler/manifest\">{json.dumps(manifest)}</script>\n\n"
        f"  <script type=\"__bundler/ext_resources\">\n{json.dumps(ext_resources or [])}\n  </script>\n\n"
        f"  <script type=\"__bundler/page_order\">\n{json.dumps(page_order or [])}\n  </script>\n\n"
        f"  <script type=\"__bundler/template\">{_script_safe(json.dumps(template))}</script>\n</body>\n</html>\n"
    )


def page_html(page: Page) -> str:
    """The inner bundle of one page."""
    runtime_id, font_id = str(uuid.uuid4()), str(uuid.uuid4())
    font_face = (
        f"@font-face {{\n  font-family: '{page.font_family}';\n  font-style: normal;\n  font-weight: 400;\n"
        f"  src: url(\"{font_id}\") format('woff2');\n}}\n"
    )
    props = {**page.props, "$preview": {"width": page.width, "height": page.height}}
    root = "x-dc" if page.is_dc else "div"
    template = (
        f"<!DOCTYPE html>\n<html lang=\"pt-BR\"><head>\n<meta charset=\"utf-8\">\n<title>{html.escape(page.title)}</title>\n"
        f"<script src=\"{runtime_id}\"></script>\n</head>\n<body>\n<{root}>\n<helmet>\n"
        f"<style>{font_face}</style>\n<style>{page.helmet_css}</style>\n</helmet>\n{page.body}\n</{root}>\n"
        f"<script type=\"text/x-dc\" data-dc-script=\"\" data-props=\"{html.escape(json.dumps(props))}\">\n"
        f"{page.logic}\n</script>\n</body></html>"
    )
    manifest = {
        runtime_id: _entry(RUNTIME_JS.encode(), "text/javascript"),
        font_id: _entry(FONT_BYTES, "font/woff2"),
    }
    return _bundle(page.title, template, manifest)


def canvas_html(pages: list[Page], title: str = "Prototype") -> str:
    """The outer bundle: a canvas of boards, one per page, in order."""
    ids = [str(uuid.uuid4()) for _ in pages]
    boards = "\n".join(
        f"<section class=\"board\"><h2>{html.escape(p.title)}</h2>"
        f"<iframe src=\"about:blank#{pid}\" title=\"{html.escape(p.title)}\" width=\"{p.width}\" "
        f"height=\"{p.height}\" loading=\"eager\" style=\"width:{p.width}px;height:{p.height}px\"></iframe></section>"
        for p, pid in zip(pages, ids)
    )
    template = (
        f"<!DOCTYPE html>\n<html lang=\"en\"><head>\n<meta charset=\"utf-8\">\n<title>{html.escape(title)}</title>\n"
        f"<style>\n.board h2{{margin:0}}\n</style>\n</head>\n<body>\n{boards}\n</body></html>"
    )
    manifest = {pid: _entry(page_html(p).encode(), "text/html") for p, pid in zip(pages, ids)}
    return _bundle(title, template, manifest, page_order=ids)
