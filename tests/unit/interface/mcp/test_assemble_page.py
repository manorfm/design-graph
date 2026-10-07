"""
assemble_page answers "build this screen" in one call: its skeleton, each
component it needs once (minus the ones the agent already has), their data,
the tokens by mode and what to install — in parts when long, never cut.
"""

import re

from design_graph.interface.mcp.assemble_tool import ASSEMBLY_PART_CHARS, assemble_page
from design_graph.interface.mcp.tools import ToolDispatcher


def _assembly(component_source="function List() { return <ul/>; }"):
    return {
        "name": "Home", "skeleton": "function Home() { return <main><Header/><List/></main>; }", "source_lang": "jsx",
        "relations": {"viewport": {"width": 390, "height": 844}, "navigates_to": [{"screen": "Fim", "label": "Seguir"}],
                      "navigated_from": [], "variant_of": None, "variants": []},
        "components": [
            {"name": "Header", "comp_type": "component", "source_code": "function Header() { return <h1/>; }",
             "source_lang": "jsx", "defined": True, "props": [], "referenced_data": {}},
            {"name": "List", "comp_type": "component", "source_code": component_source, "source_lang": "jsx",
             "defined": True, "props": [{"prop_name": "items", "default_value": "[]"}],
             "referenced_data": {"ITEMS": ["a", "b"]},
             "actions": [{"trigger": "change", "element": "input", "handler": "e => setQuery(e.target.value)",
                          "effect": "muda estado query"}]},
            {"name": "Icon", "comp_type": "component", "source_code": "", "source_lang": "", "defined": False,
             "props": [], "referenced_data": {}},
        ],
        "tokens": [
            {"t.category": "css_var", "t.label": "--ink", "t.value": "#111", "t.usage": 1, "t.mode": "claro"},
            {"t.category": "css_var", "t.label": "--ink", "t.value": "#eee", "t.usage": 1, "t.mode": "escuro"},
            {"t.category": "spacing", "t.label": "space_8", "t.value": "8px", "t.usage": 3, "t.mode": ""},
        ],
        "resources": [{"kind": "library", "name": "react", "version": "18.3.1", "origin": "https://cdn/react",
                       "certainty": "declarada", "detail": "", "size": 1, "import_line": ""}],
        "actions": [{"trigger": "click", "element": "nav", "handler": "() => setView('apps')", "effect": "muda estado view"}],
    }


class _Reader:
    def __init__(self, assembly=None):
        self.assembly = assembly or _assembly()

    def get_screen_assembly(self, name):
        return self.assembly if name == "Home" else None


def test_sections_come_in_the_contract_order():
    out = assemble_page(_Reader(), "Home")
    titles = re.findall(r"^## (.+)$", out, re.M)
    assert titles == ["1. Cabeçalho", "2. Esqueleto", "3. Componentes", "4. Dados", "5. Comportamento",
                      "6. Tokens usados, por modo", "7. Dependências", "8. Completude"]


def test_header_skeleton_and_components():
    out = assemble_page(_Reader(), "Home")
    assert "**Viewport**: 390×844" in out and "**Navega para**" in out
    assert "**Modos**: claro, escuro" in out
    assert "```jsx\nfunction Home() { return <main><Header/><List/></main>; }\n```" in out
    assert "### List" in out and "| `items` | `[]` |" in out and "function List()" in out
    assert "### Icon" in out and "sem definição no protótipo" in out


def test_data_tokens_and_dependencies():
    out = assemble_page(_Reader(), "Home")
    assert '**List** · `ITEMS`: `["a", "b"]`' in out
    assert "- **--ink**: claro `#111` · escuro `#eee`" in out
    assert "- **space_8**: `8px`" in out
    assert "- **react** 18.3.1 · https://cdn/react" in out


def test_known_components_are_left_out_and_said_so():
    out = assemble_page(_Reader(), "Home", known=["List"])
    assert "function List()" not in out
    assert "Omitidos (você já tem): List" in out


def test_a_long_assembly_comes_in_parts_that_together_hold_everything():
    long_source = "function List() {\n" + "\n".join(f"  const linha{n} = {n};" for n in range(3000)) + "\n}"
    reader = _Reader(_assembly(long_source))
    first = assemble_page(reader, "Home")
    total = int(re.search(r"parte 1/(\d+)", first).group(1))
    assert total > 1 and "Continua: assemble_page('Home', part=2)" in first
    assert "### Partes" in first
    responses = [assemble_page(reader, "Home", part=n) for n in range(1, total + 1)]
    assert all(len(r) <= ASSEMBLY_PART_CHARS + 2_000 for r in responses)
    joined = "\n".join(responses)
    assert all(f"  const linha{n} = {n};" in joined for n in range(3000))
    assert "## 8. Completude" in responses[-1]


def test_known_is_carried_to_the_next_part():
    long_source = "function List() {\n" + "\n".join(f"  const linha{n} = {n};" for n in range(3000)) + "\n}"
    first = assemble_page(_Reader(_assembly(long_source)), "Home", known=["Header"])
    assert "Continua: assemble_page('Home', part=2) — com o mesmo known" in first
    assert "known=['Header']" not in first


def test_unknown_screen_and_bad_part():
    assert "não encontrada" in assemble_page(_Reader(), "Nada")
    assert "Parte inválida" in assemble_page(_Reader(), "Home", part=9)


def test_dispatcher_passes_known_and_part():
    reader = _Reader()
    out = ToolDispatcher([("doc", reader)]).dispatch("assemble_page", {"name": "Home", "known": ["List"]}, "doc")
    assert "Omitidos (você já tem): List" in out


def test_same_named_tokens_without_modes_show_each_value_once():
    assembly = _assembly()
    assembly["tokens"] = [
        {"t.category": "radius", "t.label": "radius_xs", "t.value": "4px", "t.usage": 1, "t.mode": ""},
        {"t.category": "radius", "t.label": "radius_xs", "t.value": "2px", "t.usage": 1, "t.mode": ""},
    ]
    assert "- **radius_xs**: `4px` · `2px`" in assemble_page(_Reader(assembly), "Home")


def test_behaviour_lists_what_each_action_does_where():
    out = assemble_page(_Reader(), "Home")
    assert "- **Home** · click em `nav` → muda estado view — `() => setView('apps')`" in out
    assert "- **List** · change em `input` → muda estado query — `e => setQuery(e.target.value)`" in out
