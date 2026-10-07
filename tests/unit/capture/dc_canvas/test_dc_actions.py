"""A DC page's event attributes become actions, their handler read from the page's logic."""

import asyncio

from design_graph.capture.base import PrototypeDocument
from design_graph.capture.dc_canvas.logic import member_expression
from design_graph.capture.registry import capture_for
from tests.support.dc_canvas import Page, canvas_html

LOGIC = """class Component extends DCLogic {
  renderVals() {
    const s = this.state || {};
    const sel = s.papel ?? "eng";
    const papel = [{"id": "dir", "label": "Direção"}, {"id": "eng", "label": "Engenharia"}].map((o) => ({ ...o,
      bc: sel === o.id ? 'var(--accent)' : 'var(--rule)', pick: () => this.setState({ papel: o.id }) }));
    return { papel, next: () => this.setState({ step: 2 }) };
  }
}"""
BODY = (
    '<main><div role="group"><sc-for list="{{papel}}" as="o">'
    '<button type="button" style="border: 1px solid {{o.bc}}" sc-camel-on-click="{{o.pick}}"><span>{{o.label}}</span></button>'
    '</sc-for></div><button sc-camel-on-click="{{next}}">Continuar</button></main>'
)


def test_a_member_of_the_logic_is_read_whole():
    assert member_expression(LOGIC, "pick") == "() => this.setState({ papel: o.id })"
    assert member_expression(LOGIC, "next") == "() => this.setState({ step: 2 })"
    assert member_expression(LOGIC, "absent") is None


def _capture(tmp_path):
    path = tmp_path / "canvas.html"
    path.write_text(canvas_html([Page("1 · Papel", BODY, logic=LOGIC)]))
    document = PrototypeDocument.read(path)
    return asyncio.run(capture_for(document).capture(document, concurrency=1))


def test_an_event_inside_a_component_is_the_component_action(tmp_path):
    item = next(c for c in _capture(tmp_path).components if c.name == "PapelItem")
    assert [(a.trigger, a.element, a.handler, a.effect) for a in item.actions] == [
        ("click", "button", "() => this.setState({ papel: o.id })", "muda estado papel"),
    ]


def test_an_event_outside_components_is_the_screen_action(tmp_path):
    screen = _capture(tmp_path).screens[0]
    assert [(a.trigger, a.element, a.effect) for a in screen.actions] == [("click", "button", "muda estado step")]
