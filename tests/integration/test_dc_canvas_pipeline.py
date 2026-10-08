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
    out = _call(tools, "get_screen", name="Tela 1", detail="full")
    assert "**Navega para**: Tela 2 («Seguir»)" in out
    assert "### Tela 1" in out and "### Footer" in out


def test_repeated_footer_is_a_component_with_its_source(tools):
    out = _call(tools, "get_component", name="Footer")
    assert "```html-template" in out and "<footer" in out


def test_tokens_answer_per_mode(tools):
    out = _call(tools, "get_tokens", category="css_var", mode="escuro")
    assert "**--accent** [escuro]: `#5FB0B0`" in out and "[claro]" not in out


def test_style_references_link_to_every_mode_of_the_token(tools):
    out = _call(tools, "impact", name="--rule")
    assert "Footer" in out


TABS_LOGIC = """class Component extends DCLogic {
  renderVals() {
    const s = this.state || {};
    const tab = s.tab ?? 'cap';
    const mk = (id, label) => ({ id, label, sel: String(tab === id), pick: () => this.setState({ tab: id }) });
    const tabs = [mk('cap', 'Por capacidade'), mk('est', 'Por estrutura')];
    return { tabs };
  }
}"""
TABS_BODY = (
    '<main><div role="tablist" aria-label="Corte"><sc-for list="{{tabs}}" as="tb">'
    '<button role="tab" aria-selected="{{tb.sel}}" sc-camel-on-click="{{tb.pick}}">{{tb.label}}</button>'
    "</sc-for></div><p>Mapa</p></main>"
)


@pytest.fixture(scope="module")
def tabs_tools(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("dc_tabs")
    html_path = tmp / "canvas.html"
    html_path.write_text(canvas_html([Page("1 · Mapa", TABS_BODY, logic=TABS_LOGIC, width=1440, height=900)]))
    stats = asyncio.run(run_pipeline(html_path, tmp / "canvas.db", tmp / "canvas.db.state.json"))
    assert stats is not None and stats.write_errors == 0
    reader = GraphReader(kuzu.Connection(kuzu.Database(str(tmp / "canvas.db"), read_only=True)))
    return ToolDispatcher([("canvas", reader)]), reader


def test_copy_a_list_built_by_the_logic_holds_is_found_by_search(tabs_tools):
    out = _call(tabs_tools, "search", query="Por capacidade")
    assert "Nenhum resultado" not in out
    assert "**Por capacidade**" in out and "tabs" in out


def test_the_page_assembly_carries_the_list_the_logic_builds(tabs_tools):
    out = _call(tabs_tools, "assemble_page", name="Mapa")
    data = out.split("## 4. Dados", 1)[1].split("## 5.", 1)[0]
    assert "Por capacidade" in data and "Por estrutura" in data


def _question(n: int, list_name: str, labels: list[str]) -> Page:
    items = ", ".join(f'{{"id": "{i}", "label": "{label}"}}' for i, label in enumerate(labels))
    logic = (
        "class Component extends DCLogic {\n  renderVals() {\n"
        f"    const {list_name} = [{items}].map((o) => ({{ ...o, pick: () => this.setState({{ v: o.id }}) }}));\n"
        f"    return {{ {list_name} }};\n  }}\n}}"
    )
    body = (
        f'<main><fieldset style="border: 0; display: flex"><legend style="font-weight: 600">Pergunta {n}</legend>'
        f'<div style="display: flex; gap: 8px"><sc-for list="{{{{{list_name}}}}}" as="o">'
        '<button type="button" sc-camel-on-click="{{o.pick}}"><span>{{o.label}}</span></button>'
        f"</sc-for></div></fieldset><p>Rodapé {n}</p></main>"
    )
    return Page(f"{n} · Pergunta {n}", body, logic=logic, width=1280, height=800)


@pytest.fixture(scope="module")
def question_tools(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("dc_questions")
    html_path = tmp / "canvas.html"
    pages = [_question(1, "sen", ["Menos de 2 anos", "Mais de 10 anos"]), _question(2, "tem", ["Semanas", "Meses"]),
             _question(3, "ev", ["Registramos o que aconteceu"])]
    html_path.write_text(canvas_html(pages))
    stats = asyncio.run(run_pipeline(html_path, tmp / "canvas.db", tmp / "canvas.db.state.json"))
    assert stats is not None and stats.write_errors == 0
    reader = GraphReader(kuzu.Connection(kuzu.Database(str(tmp / "canvas.db"), read_only=True)))
    return ToolDispatcher([("canvas", reader)]), reader


def _data_section(tools, screen: str, **args) -> str:
    out = _call(tools, "assemble_page", name=screen, **args)
    return out.split("## 4. Dados", 1)[1].split("## 5.", 1)[0]


def test_the_assembly_carries_the_lists_of_components_nested_inside_another(question_tools):
    data = _data_section(question_tools, "Pergunta 2")
    assert "Semanas" in data and "Meses" in data


def test_the_assembly_carries_only_the_lists_that_screen_uses(question_tools):
    data = _data_section(question_tools, "Pergunta 2")
    assert "Menos de 2 anos" not in data and "Registramos" not in data


def test_a_screen_list_is_carried_even_when_its_components_are_already_known(question_tools):
    first = _call(question_tools, "assemble_page", name="Pergunta 1")
    known = [line.split("**Componentes**: ", 1)[1] for line in first.splitlines() if line.startswith("**Componentes**")][0]
    data = _data_section(question_tools, "Pergunta 3", known=known.split(", "))
    assert "Registramos o que aconteceu" in data


def test_a_screen_is_found_by_the_title_its_page_gives_itself(tmp_path):
    html_path = tmp_path / "canvas.html"
    html_path.write_text(canvas_html([
        Page("1 · Histórico e reavaliação", "<main><p>Comparar</p></main>", document_title="Histórico: comparar duas leituras"),
    ]))
    asyncio.run(run_pipeline(html_path, tmp_path / "canvas.db", tmp_path / "canvas.db.state.json"))
    reader = GraphReader(kuzu.Connection(kuzu.Database(str(tmp_path / "canvas.db"), read_only=True)))
    out = ToolDispatcher([("canvas", reader)]).dispatch("search", {"query": "comparar duas leituras"}, "canvas")
    assert "## Screen" in out and "**Histórico e reavaliação**" in out and "Histórico: comparar duas leituras" in out
