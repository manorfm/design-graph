"""Every event attribute of a React component or screen becomes an action: where, on what, and what it does."""

import asyncio

from design_graph.capture.html_prototype.html_capture import extract_react
from design_graph.capture.html_prototype.sources import RawSources, SourceFormat

_JS = """
function MemberForm({ onClose }) {
  const [role, setRole] = React.useState('User');
  return (
    <div>
      <input onChange={e => setRole(e.target.value)} />
      <button onClick={() => { setRole('Admin'); onClose(); }} style={{ color: '#fff' }}>Salvar</button>
      <Modal onClose={onClose} title="x" />
    </div>
  );
}
function Modal({ onClose, title }) { return <div onClick={onClose}>{title}</div>; }
function HomePage() {
  const [view, setView] = React.useState('apps');
  return (<main><nav onClick={() => setView('settings')}>Ir</nav><MemberForm onClose={() => setView('apps')} /></main>);
}
"""


def _result():
    sources = RawSources(js=_JS, css="", inner_html="", html_hash="x", format=SourceFormat.BUNDLED_REACT)
    return asyncio.run(extract_react(sources, concurrency=1))


def test_each_event_attribute_of_a_component_is_an_action():
    form = next(c for c in _result().components if c.name == "MemberForm")
    assert [(a.trigger, a.element, a.effect) for a in form.actions] == [
        ("change", "input", "muda estado role"),
        ("click", "button", "muda estado role · repassa ao pai onClose"),
        ("close", "Modal", "repassa ao pai onClose"),
    ]
    assert form.actions[1].handler == "() => { setRole('Admin'); onClose(); }"


def test_a_screen_keeps_its_own_actions():
    home = next(s for s in _result().screens if s.name == "HomePage")
    assert [(a.trigger, a.element, a.effect) for a in home.actions] == [
        ("click", "nav", "muda estado view"),
        ("close", "MemberForm", "muda estado view"),
    ]
