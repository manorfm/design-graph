"""Whole captured CSS is an explicit resource, not guessed per-component closure."""
import hashlib
from pathlib import Path

from design_graph.capture.base import PrototypeDocument
from design_graph.capture.html_prototype.parsing.source_loader import decompose
from design_graph.interface.mcp.asset_tool import get_asset


def test_captured_stylesheet_keeps_animation_reset_and_literal_bytes(tmp_path):
    css = '\n/* ação `{} */\n:root { --dur-fast: 110ms; }\n*{box-sizing:border-box}\n@keyframes pop {to{opacity:1}}\n'
    source = tmp_path / 'prototype.html'
    source.write_text(f'<!doctype html><html><head><style>{css}</style></head><body></body></html>')
    raw = decompose(PrototypeDocument.read(source))
    resource = next((r for r in raw.resources if r.name == 'prototype stylesheet'), None)
    assert resource is not None, 'CSS animations/global rules cannot be recovered from projected style rows'
    assert resource.detail == 'captured CSS in source order; external stylesheets and dependency closure unknown'
    assert len(resource.files) == 1
    asset = resource.files[0]
    assert (asset.mime, asset.content, asset.sha256) == ('text/css', css.encode(), hashlib.sha256(css.encode()).hexdigest())

    class Reader:
        def get_resource_files(self, name):
            return [{'mime': asset.mime, 'content': asset.content, 'sha256': asset.sha256}]

    output = get_asset(Reader(), resource.name, tmp_path)
    paths = list((tmp_path / 'design-graph-assets').rglob('*.css'))
    assert len(paths) == 1, output
    assert paths[0].read_bytes() == css.encode()


def test_no_stylesheet_is_not_fabricated(tmp_path):
    source = tmp_path / 'empty.html'
    source.write_text('<!doctype html><html><body>empty</body></html>')
    assert not decompose(PrototypeDocument.read(source)).resources
