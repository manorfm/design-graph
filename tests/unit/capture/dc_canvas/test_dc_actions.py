"""A DC page's event attributes become actions, their handler read from the page's logic."""

import asyncio

from design_graph.capture.base import PrototypeDocument
from design_graph.capture.dc_canvas.logic import list_member, member_expression
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


def test_a_component_action_keeps_the_binding_its_template_writes(tmp_path):
    item = next(c for c in _capture(tmp_path).components if c.name == "PapelItem")
    assert [(a.trigger, a.element, a.handler, a.effect) for a in item.actions] == [
        ("click", "button", "{{o.pick}}", "chama o.pick"),
    ]


def test_every_event_of_the_page_is_a_screen_action_read_from_its_logic(tmp_path):
    screen = _capture(tmp_path).screens[0]
    assert [(a.trigger, a.element, a.effect) for a in screen.actions] == [
        ("click", "main > div > button", "muda estado papel"), ("click", "main > button", "muda estado step"),
    ]


TWO_LISTS_LOGIC = """class Component extends DCLogic {
  renderVals() {
    const sen = [{"id": "s1"}, {"id": "s2"}].map((o) => ({ ...o, pick: () => this.setState({ sen: o.id }) }));
    const tem = [{"id": "t1"}, {"id": "t2"}].map((o) => ({ ...o, pick: () => this.setState({ tem: o.id }) }));
    return { sen, tem };
  }
}"""
TWO_LISTS_BODY = "".join(
    f'<div><sc-for list="{{{{{name}}}}}" as="o"><button sc-camel-on-click="{{{{o.pick}}}}">'
    f'<span>{{{{o.id}}}}</span></button></sc-for></div>'
    for name in ("sen", "tem")
)


def test_a_member_is_read_from_the_list_its_element_repeats(tmp_path):
    path = tmp_path / "canvas.html"
    path.write_text(canvas_html([Page("1 · Contexto", f"<main>{TWO_LISTS_BODY}</main>", logic=TWO_LISTS_LOGIC)]))
    document = PrototypeDocument.read(path)
    screen = asyncio.run(capture_for(document).capture(document, concurrency=1)).screens[0]
    assert [a.effect for a in screen.actions] == ["muda estado sen", "muda estado tem"]


def test_a_list_member_is_read_in_that_list_declaration_else_anywhere():
    assert list_member(TWO_LISTS_LOGIC, "tem", "pick") == "() => this.setState({ tem: o.id })"
    assert list_member(TWO_LISTS_LOGIC, "", "pick") == "() => this.setState({ sen: o.id })"
    assert list_member(TWO_LISTS_LOGIC, "absent", "pick") == "() => this.setState({ sen: o.id })"


def test_two_elements_doing_the_same_are_two_actions_by_where_they_are(tmp_path):
    logic = TWO_LISTS_LOGIC.replace('this.setState({ tem: o.id })', 'this.setState({ sen: o.id })')
    path = tmp_path / "canvas.html"
    path.write_text(canvas_html([Page("1 · Contexto", f"<main>{TWO_LISTS_BODY}</main>", logic=logic)]))
    document = PrototypeDocument.read(path)
    screen = asyncio.run(capture_for(document).capture(document, concurrency=1)).screens[0]
    assert [(a.element, a.effect) for a in screen.actions] == [
        ("main > div:1 > button", "muda estado sen"), ("main > div:2 > button", "muda estado sen"),
    ]
