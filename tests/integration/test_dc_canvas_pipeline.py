"""A DC canvas goes through the same pipeline, graph and MCP tools as any other prototype."""

from __future__ import annotations

import asyncio

import kuzu
import pytest

from design_graph.interface.mcp.tools import ToolDispatcher
from design_graph.model.graph.reader import GraphReader
from design_graph.pipeline.coordinator import run_pipeline
from tests.support.dc_canvas import Page, canvas_html

THEMES = ".tc{--accent:#0D5C63;--rule:#DCD4C6}\n.te{--accent:#5FB0B0;--rule:#3A3631}"
TEMA = {"tema": {"editor": "enum", "options": ["claro", "escuro"], "default": "claro"}}
FOOTER = '<footer style="border-top: 1px solid var(--rule)"><div>Sobre estas estimativas</div><div>Amostra</div></footer>'


def _page(n: int) -> Page:
    body = (
        f'<div class="{{{{t}}}}"><main><header><h1>Tela {n}</h1></header>'
        f'<div><p style="color: var(--accent)">Conteúdo {n}</p>'
        f'<a href="A0{n % 3 + 1}-Proxima.dc.html" style="color: var(--accent)">Seguir</a></div>{FOOTER}</main></div>'
    )
    return Page(f"{n} · Tela {n}", body, helmet_css=THEMES, props=TEMA)


@pytest.fixture(scope="module")
def tools(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("dc")
    html_path = tmp / "canvas.html"
    desktop = Page("1 · Tela 1 (desktop)", _page(1).body, width=1280, height=800, helmet_css=THEMES, props=TEMA)
    html_path.write_text(canvas_html([_page(1), _page(2), _page(3), desktop]))
    stats = asyncio.run(run_pipeline(html_path, tmp / "canvas.db", tmp / "canvas.db.state.json"))
    assert stats is not None and stats.write_errors == 0
    reader = GraphReader(kuzu.Connection(kuzu.Database(str(tmp / "canvas.db"), read_only=True)))
    return ToolDispatcher([("canvas", reader)]), reader


def _call(tools, tool, **args):
    return tools[0].dispatch(tool, args, "canvas")


def test_graph_records_the_dc_capture(tools):
    assert tools[1].model_info()["capture"] == "dc_canvas"


def test_screens_and_variants_are_listed(tools):
    out = _call(tools, "list_screens")
    assert "**Tela 2**" in out and "— variante de Tela 1" in out


def test_screen_shows_navigation_and_sections(tools):
    out = _call(tools, "get_screen_full", name="Tela 1")
    assert "**Navega para**: Tela 2 («Seguir»)" in out
    assert "### Tela 1" in out and "### Footer" in out


def test_repeated_footer_is_a_component_with_its_source(tools):
    out = _call(tools, "get_component", name="Footer")
    assert "```html-template" in out and "<footer" in out


def test_tokens_answer_per_mode(tools):
    out = _call(tools, "get_tokens", category="css_var", mode="escuro")
    assert "**--accent** [escuro]: `#5FB0B0`" in out and "[claro]" not in out


def test_style_references_link_to_every_mode_of_the_token(tools):
    out = _call(tools, "find_token_usage", value="--rule")
    assert "Footer" in out
