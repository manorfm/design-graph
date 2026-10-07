"""What a component or screen remembers between interactions — read where each format declares it."""

import asyncio

from design_graph.capture.html_prototype.html_capture import extract_react
from design_graph.capture.html_prototype.sources import RawSources, SourceFormat
from design_graph.capture.base import PrototypeDocument
from design_graph.capture.registry import capture_for
from design_graph.model.entities import StyleState
from tests.support.dc_canvas import Page, canvas_html

_JS = """
function MemberForm() {
  const [role, setRole] = React.useState('User');
  const [open, setOpen] = useState(false);
  return <button onClick={() => setRole('Admin')}>Salvar</button>;
}
function HomePage() {
  const [view, setView] = React.useState("apps");
  return (<main><MemberForm /></main>);
}
"""


def test_react_state_is_each_use_state_with_its_initial_value():
    sources = RawSources(js=_JS, css="", inner_html="", html_hash="x", format=SourceFormat.BUNDLED_REACT)
    result = asyncio.run(extract_react(sources, concurrency=1))
    form = next(c for c in result.components if c.name == "MemberForm")
    assert [(s.name, s.initial) for s in form.states] == [("role", "'User'"), ("open", "false")]
    assert [(s.name, s.initial) for s in result.screens[0].states] == [("view", '"apps"')]


LOGIC = """class Component extends DCLogic {
  renderVals() {
    const s = this.state || {};
    const sel_papel = s.papel ?? "eng";
    const papel = [{"id": "dir", "label": "Direção"}, {"id": "eng", "label": "Engenharia"}, {"id": "pro", "label": "Produto"}].map((o) => ({ ...o,
      bc: sel_papel === o.id ? 'var(--accent)' : 'var(--rule)', pick: () => this.setState({ papel: o.id }) }));
    return { papel };
  }
}"""
BODY = (
    '<main><div role="group"><sc-for list="{{papel}}" as="o">'
    '<button type="button" style="padding: 8px; border: 1.5px solid {{o.bc}}" sc-camel-on-click="{{o.pick}}">{{o.label}}</button>'
    '</sc-for></div><p>x</p></main>'
)


def _dc(tmp_path):
    path = tmp_path / "canvas.html"
    path.write_text(canvas_html([Page("1 · Papel", BODY, logic=LOGIC)]))
    document = PrototypeDocument.read(path)
    return asyncio.run(capture_for(document).capture(document, concurrency=1))


def test_dc_state_is_what_the_logic_reads_from_this_state_with_its_default(tmp_path):
    assert [(s.name, s.initial) for s in _dc(tmp_path).screens[0].states] == [("papel", '"eng"')]


def test_a_style_chosen_by_the_selection_becomes_the_component_selected_and_default_styles(tmp_path):
    item = next(c for c in _dc(tmp_path).components if c.name == "PapelItem")
    styles = {(s.state, s.property, s.value) for s in item.styles}
    assert (StyleState.DEFAULT, "border", "1.5px solid var(--rule)") in styles
    assert (StyleState.SELECTED, "border", "1.5px solid var(--accent)") in styles
