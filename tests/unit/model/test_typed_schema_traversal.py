"""Reuse only immutable type metadata, never an object's admission result."""
from dataclasses import dataclass

import pytest

from design_graph.model import binding_ir as ir


@dataclass(frozen=True)
class Record:
    name: str
    count: int


def test_type_schema_introspection_was_linear_in_types_not_records(monkeypatch):
    origin = ir.get_origin
    calls = []

    def tracked(expected):
        calls.append(expected)
        return origin(expected)

    monkeypatch.setattr(ir, 'get_origin', tracked)
    value = tuple(Record(str(i), i) for i in range(100))
    for invocation in (1, 2):
        ir._validate_typed(tuple[Record, ...], value)
        assert len(calls) == invocation * 4


@pytest.mark.parametrize('bad', [Record('bad', True), Record(2, 3), ['mutable']])
def test_metadata_reuse_never_reused_record_admission(bad):
    ir._validate_typed(tuple[Record, ...], (Record('ok', 1),))
    with pytest.raises(ValueError):
        ir._validate_typed(tuple[Record, ...], (Record('ok', 1), bad))
