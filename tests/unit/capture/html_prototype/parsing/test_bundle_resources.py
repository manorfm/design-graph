"""
A bundled React prototype embeds libraries, the in-browser compiler, fonts and
images next to its own code. Only its own code is read as the prototype; the
rest is described as resources.
"""

import base64
import gzip
import json
import os

from design_graph.capture.base import PrototypeDocument
from design_graph.capture.html_prototype.parsing.source_loader import decompose
from design_graph.model.entities import ResourceKind

REACT = b"/**\n * @license React\n * react.development.js\n */\nvar ReactVersion = '18.3.1';\nfunction useLibraryInternal(){}"
BABEL = b'!function(e,t){t((e=self).Babel={})}(this,function(e){function BabelInternal(){} e.transformScriptTags=V,e.version="7.29.0"})'
MODULE = (
    b"/* views.jsx v2.6 \xe2\x80\x94 app list */\nfunction AppCard() { return <div className=\"card\">App</div>; }\n"
    b"function HomePage() { return (<main><AppCard /></main>); }\n"
)
FONT = b"wOF2" + b"\x00\xff" * 50
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><circle r="4"/></svg>'
TEMPLATE = """<!DOCTYPE html><html><head>
<link rel="icon" type="image/svg+xml" href="icon-1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<style>
/* latin */
@font-face { font-family: 'IBM Plex Sans'; font-style: normal; font-weight: 400; src: url("font-1") format('woff2'); }
body { margin: 0 }
</style>
<script src="react-1"></script><script src="babel-1"></script><script type="text/babel" src="views-1"></script>
</head><body><div id="root"></div></body></html>"""


def _entry(content: bytes, mime: str) -> dict:
    return {"data": base64.b64encode(gzip.compress(content)).decode(), "compressed": True, "mime": mime}


def _sources(tmp_path):
    manifest = {
        "index": _entry(TEMPLATE.encode(), "text/html"),
        "react-1": _entry(REACT, "application/javascript"),
        "babel-1": _entry(BABEL, "application/javascript"),
        "views-1": _entry(MODULE, "text/jsx"),
        "font-1": _entry(FONT, "font/woff2"),
        "icon-1": _entry(SVG, "image/svg+xml"),
        # An unreferenced binary: real bundles run to megabytes, past the loader's size threshold.
        "padding": _entry(os.urandom(12_000), "application/octet-stream"),
    }
    path = tmp_path / "proto.html"
    path.write_text(f"<html><body><script>{json.dumps(manifest)}</script></body></html>")
    return decompose(PrototypeDocument.read(path))


def test_only_the_prototype_own_code_is_read_as_code(tmp_path):
    js = _sources(tmp_path).js
    assert "function AppCard" in js
    assert "useLibraryInternal" not in js and "BabelInternal" not in js
    assert "wOF2" not in js and "<circle" not in js


def test_everything_it_loads_is_described(tmp_path):
    found = {(r.kind, r.name, r.version) for r in _sources(tmp_path).resources}
    assert found == {
        (ResourceKind.LIBRARY, "react", "18.3.1"),
        (ResourceKind.RUNTIME, "@babel/standalone", "7.29.0"),
        (ResourceKind.MODULE, "views.jsx", "v2.6"),
        (ResourceKind.FONT, "IBM Plex Sans", ""),
        (ResourceKind.IMAGE, "favicon", ""),
    }


def test_font_bytes_and_origin_come_from_the_page(tmp_path):
    font = next(r for r in _sources(tmp_path).resources if r.kind == ResourceKind.FONT)
    assert (font.size, font.origin, font.detail) == (len(FONT), "Google Fonts", "pesos 400 · normal · subconjuntos latin")


def test_every_screen_of_a_single_page_app_loads_every_resource(tmp_path):
    import asyncio

    from design_graph.capture.registry import capture_for

    _sources(tmp_path)  # writes proto.html
    document = PrototypeDocument.read(tmp_path / "proto.html")
    result = asyncio.run(capture_for(document).capture(document, concurrency=1))
    ids = {r.id for r in result.resources}
    assert len(ids) == 5
    assert [set(screen.resource_ids) for screen in result.screens] == [ids]
