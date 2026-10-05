"""
What a prototype loads besides its own code — libraries, the design tool's
runtime, fonts, images — identified from the files themselves, never fetched.
"""

import hashlib

from design_graph.capture.resources import font_resources, image_resource, script_resource
from design_graph.model.entities import Certainty, ResourceKind

REACT = b"/**\n * @license React\n * react.development.js\n */\nvar ReactVersion = '18.3.1';\nfunction createElement(){}"
REACT_DOM = b"/**\n * @license React\n * react-dom.production.min.js\n */\nvar ReactVersion = '18.3.1';"
BABEL = b'!function(e,t){t((e=self).Babel={})}(this,function(e){F.version="3.0.2";e.transformScriptTags=V,e.version="7.29.0"})'
DC_RUNTIME = b"// GENERATED from dc-runtime/src/*.ts - do not edit.\n\"use strict\";(()=>{})();"
QR = b"//---------\n//\n// QR Code Generator for JavaScript\n//\n// Copyright (c) 2009 Kazuhiko Arase\nvar qrcode = function(){};"
MODULE = b"/* views.jsx v2.6 \xe2\x80\x94 app list, edit drawer, keys */\nfunction AppCard() { return <div/>; }"


def test_libraries_are_named_with_their_version():
    react = script_resource("e1", REACT)
    assert (react.kind, react.name, react.version) == (ResourceKind.LIBRARY, "react", "18.3.1")
    assert script_resource("e2", REACT_DOM).name == "react-dom"
    assert (script_resource("e3", QR).kind, script_resource("e3", QR).name) == (ResourceKind.LIBRARY, "qrcode-generator")


def test_the_design_tool_runtime_is_runtime():
    assert (script_resource("b", BABEL).kind, script_resource("b", BABEL).name, script_resource("b", BABEL).version) == (
        ResourceKind.RUNTIME, "@babel/standalone", "7.29.0")
    assert (script_resource("r", DC_RUNTIME).kind, script_resource("r", DC_RUNTIME).name) == (ResourceKind.RUNTIME, "dc-runtime")


def test_anything_else_is_a_module_of_the_prototype_named_by_its_heading():
    module = script_resource("m", MODULE)
    assert (module.kind, module.name, module.version) == (ResourceKind.MODULE, "views.jsx", "v2.6")


def test_a_known_url_is_the_stated_origin_otherwise_it_is_embedded():
    url = "https://cdn.jsdelivr.net/npm/react@18.3.1/umd/react.production.min.js"
    stated = script_resource("e1", REACT, url=url)
    assert (stated.origin, stated.certainty) == (url, Certainty.STATED)
    assert script_resource("e1", REACT).origin == "embutido no protótipo"


def test_size_and_hash_describe_the_file():
    react = script_resource("e1", REACT)
    assert react.size == len(REACT) and react.sha256 == hashlib.sha256(REACT).hexdigest()


def test_the_same_library_is_one_resource_wherever_it_is_embedded():
    assert script_resource("a", REACT).id == script_resource("b", REACT).id


FONT_CSS = """
/* latin-ext */
@font-face {
  font-family: 'IBM Plex Sans';
  font-style: normal;
  font-weight: 400;
  src: url("f1") format('woff2');
}
/* latin */
@font-face {
  font-family: 'IBM Plex Sans';
  font-style: normal;
  font-weight: 600;
  src: url("f2") format('woff2');
}
@font-face {
  font-family: "JetBrains Mono";
  font-style: italic;
  font-weight: 400;
  src: url("f3") format('woff2');
}
"""


def test_fonts_are_described_per_family_with_weights_styles_and_subsets():
    fonts = {f.name: f for f in font_resources(FONT_CSS, {"f1": b"x" * 10, "f2": b"y" * 20, "f3": b"z"})}
    plex = fonts["IBM Plex Sans"]
    assert plex.kind == ResourceKind.FONT
    assert plex.detail == "pesos 400, 600 · normal · subconjuntos latin, latin-ext"
    assert plex.size == 30
    assert fonts["JetBrains Mono"].detail == "pesos 400 · italic"


def test_font_origin_is_inferred_from_the_page_hints_and_says_so():
    plex = font_resources(FONT_CSS, {}, hints='<link rel="preconnect" href="https://fonts.googleapis.com">')[0]
    assert (plex.origin, plex.certainty) == ("Google Fonts", Certainty.INFERRED)
    assert font_resources(FONT_CSS, {})[0].origin == "embutido no protótipo"


def test_images_keep_their_role_and_size():
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"/>'
    favicon = image_resource("i1", svg, "image/svg+xml", "favicon")
    assert (favicon.kind, favicon.name, favicon.detail, favicon.size) == (ResourceKind.IMAGE, "favicon", "image/svg+xml", len(svg))


def test_babel_is_recognized_by_its_umd_global_and_versioned_by_its_export():
    babel = b'!function(e,t){t((e=self).Babel={})}(this,function(e){F.version="3.0.2";e.transformFromAst=X,e.transformScriptTags=V,e.version="7.29.0"})'
    assert (script_resource("b", babel).name, script_resource("b", babel).version) == ("@babel/standalone", "7.29.0")


def test_a_module_named_inside_its_opening_comment():
    tweaks = b"\n/* BEGIN USAGE */\n// tweaks-panel.jsx\n// Reusable Tweaks shell.\nfunction TweaksPanel() {}"
    assert script_resource("t", tweaks).name == "tweaks-panel.jsx"


def test_a_module_without_a_file_name_is_named_by_its_first_heading_line():
    framed = "/* ═════════════\n   iPede Manager v21 — ONBOARDING: presets por tipo\n   ═════════════ */\nconst A = 1;".encode()
    assert script_resource("m", framed).name == "iPede Manager v21 — ONBOARDING: presets por tipo"


def test_a_module_starting_with_code_is_named_by_its_id():
    assert script_resource("3c7ac179-aaaa", b"const { useState } = React;\n/* \xe2\x94\x80 TOKENS */").name == "módulo 3c7ac179"
