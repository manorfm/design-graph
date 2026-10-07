"""A prototype's own hooks: each whole, with what it remembers and does, and who calls it."""

from design_graph.capture.html_prototype.extraction.hook_extractor import extract_hooks, hooks_called
from design_graph.capture.html_prototype.parsing.js_parser import find_hook_boundaries
from design_graph.model.entities import ComponentType

JS = """
function useEscClose(onClose) {
  React.useEffect(() => { const h = (e) => e.key === 'Escape' && onClose(); return () => {}; }, [onClose]);
}
const useDirtyGuard = (current) => {
  const [pendingClose, setPendingClose] = React.useState(null);
  useEscClose(() => setPendingClose(null));
  return <Confirm onCancel={() => setPendingClose(null)} />;
};
function Panel() { const guard = useDirtyGuard(1); return <div>{guard}</div>; }
"""


def test_hooks_are_found_in_both_declaration_forms():
    assert [b.name for b in find_hook_boundaries(JS)] == ["useEscClose", "useDirtyGuard"]


def test_a_hook_comes_whole_with_its_states_actions_and_the_hooks_it_calls():
    hooks = {h.name: h for h in extract_hooks(JS, find_hook_boundaries(JS))}
    guard = hooks["useDirtyGuard"]
    assert guard.comp_type == ComponentType.HOOK and guard.source_lang == "jsx"
    assert guard.source_code.startswith("const useDirtyGuard") and guard.source_code.endswith("/>;\n}")
    assert [s.name for s in guard.states] == ["pendingClose"]
    assert [(a.trigger, a.effect) for a in guard.actions] == [("cancel", "muda estado pendingClose")]
    assert guard.hook_refs == ["useEscClose"] and guard.occurrence == 1


def test_who_calls_a_hook_never_counts_its_own_declaration():
    names = ["useEscClose", "useDirtyGuard"]
    assert hooks_called("function Panel() { const g = useDirtyGuard(1); useDirtyGuard(2); }", names) == ["useDirtyGuard"]
    assert hooks_called("function useEscClose(onClose) {}", names) == []


def test_the_capture_keeps_hooks_and_links_who_calls_them():
    import asyncio

    from design_graph.capture.html_prototype.html_capture import extract_react
    from design_graph.capture.html_prototype.sources import RawSources, SourceFormat

    js = JS + "function HomePage() { useEscClose(() => {}); return <main><Panel/></main>; }"
    sources = RawSources(js=js, css="", inner_html="", html_hash="x", format=SourceFormat.BUNDLED_REACT)
    result = asyncio.run(extract_react(sources, concurrency=1))
    by_name = {c.name: c for c in result.components}
    assert by_name["useDirtyGuard"].comp_type == ComponentType.HOOK
    assert by_name["Panel"].hook_refs == ["useDirtyGuard"]
    assert next(s for s in result.screens if s.name == "HomePage").hook_refs == ["useEscClose"]
