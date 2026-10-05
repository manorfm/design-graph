"""
A React component's and screen's stored source is the function exactly as the
prototype wrote it — hooks, handlers, lists and conditions included — not a
simplification with markers in place of the logic.
"""

import asyncio

from design_graph.capture.html_prototype.html_capture import extract_react
from design_graph.capture.html_prototype.sources import RawSources, SourceFormat

_JS = """
function Row({ item }) { return <li>{item.label}</li>; }
function Empty() { return <p>Nada</p>; }
function ItemList({ items }) {
  const [open, setOpen] = React.useState(false);
  return (
    <ul onClick={() => { setOpen(!open); console.log('toggled', open); }}>
      {items.map(item => <Row key={item.id} item={item} />)}
      {items.length === 0 && <Empty />}
    </ul>
  );
}
function HomePage() {
  const [tab, setTab] = React.useState('a');
  return (<main>{tab === 'a' ? <ItemList items={[]} /> : <Empty />}</main>);
}
"""


def _result():
    sources = RawSources(js=_JS, css="", inner_html="", html_hash="x", format=SourceFormat.BUNDLED_REACT)
    return asyncio.run(extract_react(sources, concurrency=1))


def _function(name: str) -> str:
    start = _JS.index(f"function {name}(")
    end = _JS.index("\n}\n", start) + 2
    return _JS[start:end]


def test_component_source_is_its_function_as_written():
    item_list = next(c for c in _result().components if c.name == "ItemList")
    assert item_list.source_code == _function("ItemList")


def test_children_behind_lists_and_conditions_are_still_found():
    item_list = next(c for c in _result().components if c.name == "ItemList")
    assert {"Row", "Empty"} <= set(item_list.child_refs)


def test_screen_source_is_its_function_as_written():
    home = next(s for s in _result().screens if s.name == "HomePage")
    assert home.source_code == _function("HomePage")


def test_the_model_no_longer_marks_sources_as_simplified():
    from design_graph.model.entities import ExtractedComponent, ExtractedScreen
    from design_graph.model.graph.schema import node_tables

    assert not hasattr(ExtractedComponent, "source_simplified")
    assert not hasattr(ExtractedScreen, "source_simplified")
    assert "source_simplified" not in node_tables()["Component"].columns
