"""get_resources tells an agent what to declare, what to fetch and what never to reproduce."""

from design_graph.interface.mcp.discovery_tools import get_resources
from design_graph.interface.mcp.tools import ToolDispatcher

_ROWS = [
    {"kind": "library", "name": "react", "version": "18.3.1", "origin": "https://cdn/react", "certainty": "declarada",
     "detail": "", "size": 109931},
    {"kind": "runtime", "name": "@babel/standalone", "version": "7.29.0", "origin": "embutido no protótipo",
     "certainty": "declarada", "detail": "", "size": 3137752},
    {"kind": "font", "name": "IBM Plex Sans", "version": "", "origin": "Google Fonts", "certainty": "inferida",
     "detail": "pesos 400, 600 · normal", "size": 0,
     "import_line": '@import url("https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600&display=swap");'},
    {"kind": "module", "name": "views.jsx", "version": "v2.6", "origin": "embutido no protótipo", "certainty": "inferida",
     "detail": "", "size": 40411},
]


class _Reader:
    def __init__(self):
        self.asked = None

    def get_resources(self, kind=None, screen=None):
        self.asked = (kind, screen)
        return [r for r in _ROWS if kind in (None, r["kind"])]


def test_resources_are_grouped_by_what_to_do_with_them():
    out = get_resources(_Reader(), None, None)
    assert "## Bibliotecas (declarar no projeto, não copiar)" in out
    assert "- **react** 18.3.1 · https://cdn/react" in out
    assert "## Não reproduzir (infraestrutura do protótipo)" in out and "@babel/standalone" in out
    assert "- **IBM Plex Sans** · pesos 400, 600 · normal · Google Fonts (inferida)" in out
    assert '  `@import url("https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600&display=swap");`' in out
    assert "## Módulos do protótipo" in out and "views.jsx" in out


def test_nothing_found_says_so():
    assert "Nenhum recurso" in get_resources(_Reader(), "image", None)


def test_dispatcher_passes_kind_and_screen():
    reader = _Reader()
    ToolDispatcher([("doc", reader)]).dispatch("get_resources", {"kind": "font", "screen": "Home"}, "doc")
    assert reader.asked == ("font", "Home")
