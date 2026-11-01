"""Synthetic capture-contract controls; no engine process or database opens."""
import asyncio
import json
from hashlib import sha256
from types import SimpleNamespace

import pytest

from design_graph.capture import registry
from design_graph.capture.base import PrototypeDocument


def test_binding_session_was_selected_through_capture_contract(tmp_path, monkeypatch):
    factory = getattr(registry, 'binding_capture_for', None)
    assert callable(factory), 'binding pipeline has no capture contract for whole-unit ownership'
    from design_graph.capture import binding_capture
    assets = tmp_path / 'assets'
    assets.mkdir()
    pin = {'version': 'synthetic', 'files': {}}
    (assets / 'source-syntax-pin.json').write_text(json.dumps(pin))
    (assets / 'capture.mjs').write_text('// synthetic asset, never executed')
    producer = SimpleNamespace(assets=assets, capture_source_syntax=lambda *a, **kw: (a, kw))
    monkeypatch.setattr(binding_capture, 'BindingCapture', lambda **kw: producer)
    path = tmp_path / 'source.html'
    path.write_text('<html><script> const x=1; </script><script src="external.js"></script></html>')
    document = PrototypeDocument.read(path)
    session = factory(document, node=tmp_path / 'node', toolchain=tmp_path, fingerprint='a' * 64)
    assert [u.source for u in session.units] == [b' const x=1; ']
    assert [r['status'] for r in session.coverage] == ['selected', 'excluded']
    assert session.syntax_fingerprint == sha256(json.dumps(pin, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert session.adaptor['capture.mjs'] == sha256((assets / 'capture.mjs').read_bytes()).hexdigest()
    for module in ('binding_capture.py', 'binding_units.py'):
        assert module in session.adaptor
    events = []
    assert session.capture_source_syntax(b'x', locator='pure:x', source_type='script', syntax='js', owner_events=events) == ((b'x',), {'locator': 'pure:x', 'source_type': 'script', 'syntax': 'js', 'owner_events': events})


@pytest.mark.parametrize('translated', [True, False])
def test_general_capture_kept_owned_and_unsupported_routes(tmp_path, monkeypatch, translated):
    factory = getattr(registry, 'binding_capture_for', None)
    assert callable(factory), 'binding pipeline has no capture contract for whole-unit ownership'
    from design_graph.capture import binding_capture, owned_emission, owned_html_capture
    from design_graph.capture.html_prototype import html_capture
    from design_graph.capture.html_prototype.parsing import source_loader
    assets = tmp_path / 'assets'
    assets.mkdir()
    (assets / 'source-syntax-pin.json').write_text('{}')
    monkeypatch.setattr(binding_capture, 'BindingCapture', lambda **kw: SimpleNamespace(assets=assets))
    path = tmp_path / 'source.html'
    path.write_text('<html><script> const x=1; </script></html>')
    document = PrototypeDocument.read(path)
    session = factory(document, node=tmp_path / 'node', toolchain=tmp_path, fingerprint='a' * 64)
    monkeypatch.setattr(source_loader, 'decompose', lambda doc: SimpleNamespace(js='const x=1;' if translated else 'different'))
    calls = []
    def boundaries(*args):
        calls.append(args)
        return 'native-boundaries'
    monkeypatch.setattr(owned_emission, 'native_boundaries', boundaries)
    class General:
        async def capture(self, doc, **kwargs):
            assert doc is document and kwargs == {'concurrency': 2}
            return ('general', getattr(self, 'boundaries', None))
    class Owned(General):
        def __init__(self, value):
            self.boundaries = value
    monkeypatch.setattr(html_capture, 'HtmlPrototypeCapture', General)
    monkeypatch.setattr(owned_html_capture, 'OwnedHtmlPrototypeCapture', Owned)
    captures, events = ('synthetic-syntax',), [('synthetic-event',)]
    result = asyncio.run(session.capture_general(captures, events, concurrency=2))
    assert result == ('general', 'native-boundaries' if translated else None)
    assert calls == [(session.units, captures, events, 'const x=1;')] if translated else calls == []
