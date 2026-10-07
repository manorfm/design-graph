"""Everything needed to build one screen, read in one go: its own source, each component it uses once, and what they need."""

import kuzu
import pytest

from design_graph.model.entities import (
    Certainty, ComponentProp, DesignToken, ExtractedComponent, ExtractedScreen, Resource, ResourceKind, StyleEntry,
)
from design_graph.model.graph.reader import GraphReader
from design_graph.model.graph.schema import initialize_schema
from design_graph.model.graph.writer import GraphWriter

REACT = Resource.create(ResourceKind.LIBRARY, "react", "18.3.1", origin="embutido no protótipo", certainty=Certainty.STATED)


def _comp(name, source, child_refs=(), styles=(), **extra):
    return ExtractedComponent(name=name, comp_type="component", source_code=source, occurrence=1, classes="",
                              child_refs=list(child_refs), styles=list(styles), source_lang="jsx", **extra)


@pytest.fixture()
def reader(tmp_path):
    conn = kuzu.Connection(kuzu.Database(str(tmp_path / "assembly.db")))
    initialize_schema(conn)
    w = GraphWriter(conn)
    w.write_tokens([
        DesignToken(id="ink_c", category="css_var", label="--ink", value="#111", usage=1, mode="claro"),
        DesignToken(id="ink_e", category="css_var", label="--ink", value="#eee", usage=1, mode="escuro"),
    ])
    w.write_resources([REACT])
    w.write_component(_comp("Row", "function Row() { return <li/>; }"))
    w.write_component(_comp("List", "function List() { return <ul><Row/><Row/></ul>; }", child_refs=["Row"],
                            styles=[StyleEntry.create("List", "color", "var(--ink)")],
                            referenced_data={"ITEMS": [1, 2]},
                            props=[ComponentProp.create("List", "items", "[]")]))
    w.write_component(_comp("Header", "function Header() { return <h1/>; }"))
    w.write_screen(ExtractedScreen(name="Home", component_refs=["Header", "List"], sections_count=0,
                                   source_code="function Home() { return <main><Header/><List/></main>; }",
                                   source_lang="jsx", viewport_width=390, viewport_height=844,
                                   resource_ids=[REACT.id]), [])
    w.commit()
    return GraphReader(conn)


def test_the_screen_own_source_is_the_skeleton(reader):
    assembly = reader.get_screen_assembly("Home")
    assert assembly["skeleton"] == "function Home() { return <main><Header/><List/></main>; }"
    assert (assembly["source_lang"], assembly["relations"]["viewport"]) == ("jsx", {"width": 390, "height": 844})


def test_each_component_comes_once_in_the_order_the_screen_renders_it(reader):
    components = reader.get_screen_assembly("Home")["components"]
    assert [c["name"] for c in components] == ["Header", "List", "Row"]
    listing = components[1]
    assert listing["source_code"].startswith("function List()") and listing["referenced_data"] == {"ITEMS": [1, 2]}


def test_tokens_and_resources_are_the_screen_own(reader):
    assembly = reader.get_screen_assembly("Home")
    assert {(t["t.label"], t["t.mode"]) for t in assembly["tokens"]} == {("--ink", "claro"), ("--ink", "escuro")}
    assert [r["name"] for r in assembly["resources"]] == ["react"]


def test_unknown_screen_has_no_assembly(reader):
    assert reader.get_screen_assembly("Nada") is None


def test_a_component_already_written_out_inside_another_is_not_sent_again(tmp_path):
    conn = kuzu.Connection(kuzu.Database(str(tmp_path / "nested.db")))
    initialize_schema(conn)
    w = GraphWriter(conn)
    w.write_component(_comp("FooterLink", '<a href="{{slot.href}}">{{slot.texto}}</a>'))
    w.write_component(_comp("Footer", '<footer><a href="x">Sobre</a></footer>', child_refs=["FooterLink"]))
    w.write_screen(ExtractedScreen(name="Page", component_refs=["Footer"], sections_count=0,
                                   source_code="<main><footer><a href='x'>Sobre</a></footer></main>",
                                   skeleton="<main><Footer></Footer></main>"), [])
    w.commit()
    assembly = GraphReader(conn).get_screen_assembly("Page")
    assert assembly["skeleton"] == "<main><Footer></Footer></main>"
    assert [c["name"] for c in assembly["components"]] == ["Footer"]


def test_components_are_the_ones_the_skeleton_uses_as_tags_not_words_in_its_text(tmp_path):
    conn = kuzu.Connection(kuzu.Database(str(tmp_path / "tags.db")))
    initialize_schema(conn)
    w = GraphWriter(conn)
    w.write_component(_comp("Projeto", "<div>muito markup</div>"))
    w.write_component(_comp("Cell", '<i style="background: {{slot.background}}"></i>'))
    w.write_screen(ExtractedScreen(name="Page", component_refs=["Projeto"], sections_count=0,
                                   source_code="<main><p>Projeto novo</p><i></i></main>",
                                   skeleton='<main><p>Projeto novo</p><Cell background="red"></Cell></main>'), [])
    w.commit()
    assert [c["name"] for c in GraphReader(conn).get_screen_assembly("Page")["components"]] == ["Cell"]


def test_actions_are_read_with_their_component_and_screen(tmp_path):
    from design_graph.model.entities import Action

    click = Action.create("Btn", "click", "button", "() => setOpen(true)", "muda estado open")
    nav = Action.create("Page", "click", "nav", "() => setView('apps')", "muda estado view")
    conn = kuzu.Connection(kuzu.Database(str(tmp_path / "actions.db")))
    initialize_schema(conn)
    w = GraphWriter(conn)
    w.write_component(_comp("Btn", "function Btn() { return <button/>; }", actions=[click]))
    w.write_screen(ExtractedScreen(name="Page", component_refs=["Btn"], sections_count=0,
                                   source_code="<main><Btn/></main>", actions=[nav]), [])
    w.commit()
    reader = GraphReader(conn)
    expected_click = {"trigger": "click", "element": "button", "handler": "() => setOpen(true)", "effect": "muda estado open"}
    assert reader.get_component_spec("Btn")["actions"] == [expected_click]
    assembly = reader.get_screen_assembly("Page")
    assert assembly["actions"] == [{"trigger": "click", "element": "nav", "handler": "() => setView('apps')",
                                    "effect": "muda estado view"}]
    assert assembly["components"][0]["actions"] == [expected_click]
