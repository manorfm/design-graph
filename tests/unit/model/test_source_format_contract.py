"""Closed wire source kinds are shared by capture and parser-free read admission."""
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from design_graph.model.binding_capture_ir import BindingCaptureIR
from tests.unit.model.test_syntax_preparation_audits import snapshot


def test_source_kind_used_one_explicit_wire_contract():
    import importlib.util
    assert importlib.util.find_spec('design_graph.source_contract') is not None, 'shared wire source-kind contract is absent'
    from design_graph import source_contract
    contract = getattr(source_contract, 'BINDING_CAPTURE_V3', None)
    assert contract is not None, 'producer and persisted model have no shared wire source-kind contract'
    assert contract.version == 'binding-capture/3'
    assert contract.source_types == ('script', 'module')
    assert contract.syntaxes == ('js', 'jsx')


@pytest.mark.parametrize('source_type', ['script', 'module'])
@pytest.mark.parametrize('syntax', ['js', 'jsx'])
def test_existing_source_kinds_kept_exact_wire_bytes(source_type, syntax):
    capture = replace(snapshot().captures[0].lexical, source_type=source_type, syntax=syntax)
    # Source-unit ids are checked at snapshot admission, not standalone profile admission.
    text = capture.to_json()
    data = json.loads(text)
    assert data['source_type'] == source_type and data['syntax'] == syntax
    assert BindingCaptureIR.from_json(text).to_json() == text


@pytest.mark.parametrize('source_type,syntax', [('unknown', 'js'), ('script', 'ts'), ('script', ''), (True, 'js'), ('script', 1), ('script', ['js'])])
def test_unsupported_or_mistyped_kind_was_rejected_independently(source_type, syntax):
    capture = replace(snapshot().captures[0].lexical, source_type=source_type, syntax=syntax)
    with pytest.raises(ValueError):
        capture.check()
    data = json.loads(snapshot().captures[0].lexical.to_json())
    data.update(source_type=source_type, syntax=syntax)
    with pytest.raises(ValueError):
        BindingCaptureIR.from_json(json.dumps(data))


def test_both_producer_entries_admitted_kind_before_native_execution():
    from design_graph.capture.binding_capture import BindingCapture
    from design_graph.capture.source_syntax_capture import capture_source_syntax
    def forbidden(*args, **kwargs):
        raise AssertionError('unsupported kind reached native engine')
    producer = SimpleNamespace(_verify_toolchain=forbidden)
    for source_type, syntax in [('script', 'ts'), ('unknown', 'jsx')]:
        with pytest.raises(ValueError):
            BindingCapture._capture_snapshot_unit(producer, b'const x=1;', locator='pure:x', source_type=source_type, syntax=syntax)
        with pytest.raises(ValueError):
            capture_source_syntax(producer, b'const x=1;', locator='pure:x', source_type=source_type, syntax=syntax)
