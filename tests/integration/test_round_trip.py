"""
Round-trip: what the tools return as a source is what the prototype wrote —
every function of a React prototype and every part of a DC page comes back
verbatim, across as many get_full_source pages as it takes.
"""

from __future__ import annotations

import asyncio
import re

import kuzu

from design_graph.interface.mcp.full_tools import MID_LINE_NOTICE, get_full_source
from design_graph.model.graph.reader import GraphReader
from design_graph.pipeline.coordinator import run_pipeline
from tests.support.dc_canvas import Page, canvas_html

_ICON = '<svg width="16" height="16" viewBox="0 0 16 16"><path d="M2 2 L14 14"/></svg>'
_FUNCTIONS = {
    "Row": "function Row({ item }) {\n  return <li onClick={() => select(item.id)}>{item.label}</li>;\n}",
    "Empty": "function Empty() {\n  return <p className=\"empty\">Nada por aqui — " + "texto longo " * 2000 + "</p>;\n}",
    "ItemList": (
        "function ItemList({ items }) {\n  const [open, setOpen] = React.useState(false);\n"
        f"  return (<ul>{_ICON}{{items.map(i => <Row key={{i.id}} item={{i}} />)}}{{!items.length && <Empty />}}</ul>);\n}}"
    ),
    "HomePage": "function HomePage() {\n  return (<main><ItemList items={[]} /></main>);\n}",
}
_REACT = (
    "<!DOCTYPE html><html><head><script src=\"react.js\"></script></head><body><div id=\"root\"></div>"
    "<script type=\"text/babel\">\n" + "\n\n".join(_FUNCTIONS.values())
    + "\nReactDOM.render(<HomePage />, document.getElementById('root'));\n</script></body></html>"
)


def _build(tmp_path, html: str) -> GraphReader:
    path = tmp_path / "proto.html"
    path.write_text(html)
    stats = asyncio.run(run_pipeline(path, tmp_path / "proto.db", tmp_path / "proto.db.state.json"))
    assert stats is not None and stats.write_errors == 0
    return GraphReader(kuzu.Connection(kuzu.Database(str(tmp_path / "proto.db"), read_only=True)))


def _whole_source(reader: GraphReader, name: str) -> str:
    """Every page of get_full_source, joined back — what an agent reading them all gets."""
    first = get_full_source(reader, name)
    total = int(m.group(1)) if (m := re.search(r"página 1/(\d+)", first)) else 1
    source = ""
    for n in range(1, total + 1):
        response = get_full_source(reader, name, page=n)
        source += re.search(r"```[\w-]*\n(.*)\n```", response, re.S).group(1)
        if n < total:
            source += "" if MID_LINE_NOTICE in response else "\n"
    return source


def test_every_react_function_comes_back_verbatim(tmp_path):
    reader = _build(tmp_path, _REACT)
    for name, function in _FUNCTIONS.items():
        assert function in _whole_source(reader, name), name


def test_every_part_of_a_dc_page_comes_back_verbatim(tmp_path):
    pages = [
        Page("1 · Início", '<div style="display: flex"><h1>Início</h1><p style="color: var(--ink)">' + "Olá. " * 3000 + "</p></div>",
             helmet_css=".tema-escuro { --ink: #EDE8DF; }"),
        Page("2 · Fim", '<div><ul><li>a</li><li>b</li></ul><a href="A01-Inicio.dc.html">Voltar</a></div>'),
    ]
    reader = _build(tmp_path, canvas_html(pages))
    for page in pages:
        source = _whole_source(reader, page.title.split(" · ", 1)[1])
        assert page.body in source
        assert page.helmet_css in source
        assert page.logic in source
