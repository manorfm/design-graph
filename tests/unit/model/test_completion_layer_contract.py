"""Completion reads and emission keys must not load build orchestration."""
import json
from hashlib import sha256

import pytest
import os
from pathlib import Path
import subprocess
import sys


def test_model_completion_and_emission_worked_without_pipeline(tmp_path):
    script = '''
import importlib.abc
import sys
from types import SimpleNamespace
class NoPipeline(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname == 'design_graph.pipeline' or fullname.startswith('design_graph.pipeline.'):
            raise AssertionError('model loaded build orchestration: ' + fullname)
sys.meta_path.insert(0, NoPipeline())
from design_graph.model.source_owner import emitted
witness = emitted('Component', 'é😀', 'payload', None, 'payload')
assert witness.key == '["\\\\u00e9\\\\ud83d\\\\ude00"]'
from design_graph.model.graph.source_build_ownership import _read_source_build_facts
try:
    _read_source_build_facts(SimpleNamespace(_state_path=None))
except ValueError as exc:
    assert 'no retained build completion' in str(exc)
else:
    raise AssertionError('missing completion was admitted')
'''
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[3] / 'src'))
    result = subprocess.run([sys.executable, '-c', script], env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('raw', [b'{"key":1,"key":2}', b'[]', b'[' * 65 + b'0' + b']' * 65, b' ' * (2 * 1024 * 1024 + 1)])
def test_completion_transport_kept_independent_limits(tmp_path, raw):
    from design_graph.model.graph.binding_completion import read_completion
    path = tmp_path / 'completion.json'
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        read_completion(path)


def test_model_serialization_kept_exact_types_and_bytes():
    from design_graph.model.serialization import canonical
    assert canonical({'z': True, 'a': ['é😀', 1]}) == '{"a":["\\u00e9\\ud83d\\ude00",1],"z":true}'
    assert canonical(True) != canonical(1)
    for value in (float('nan'), float('inf')):
        with pytest.raises(ValueError):
            canonical(value)


def test_producer_contract_dependencies_remained_custody_pinned():
    root = Path(__file__).parents[3] / 'src' / 'design_graph'
    pin = json.loads((root / 'capture/binding_engine/source-syntax-pin.json').read_text())
    assert 'model/serialization.py' in pin['files']
    for path, digest in pin['files'].items():
        assert sha256((root / path).read_bytes()).hexdigest() == digest, path
