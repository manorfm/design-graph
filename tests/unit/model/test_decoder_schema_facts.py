"""Decoder schema reuse never reuses payload admission."""
from collections import Counter
from dataclasses import dataclass

import pytest

from design_graph.model import binding_ir as ir


@dataclass(frozen=True)
class Record:
    number: int
    label: str


@dataclass(frozen=True)
class Envelope:
    records: tuple[Record, ...]
    optional: Record | None


def payload():
    return {"records": [{"number": n, "label": str(n)} for n in range(12)], "optional": None}


def test_schema_resolution_is_per_type_per_decode_not_per_record(monkeypatch):
    counts = Counter()
    original = ir.get_type_hints

    def observe(cls):
        counts[cls] += 1
        return original(cls)

    monkeypatch.setattr(ir, "get_type_hints", observe)
    first = ir._decode(Envelope, payload())
    assert len(first.records) == 12
    assert counts == {Envelope: 1, Record: 1}
    assert ir._decode(Envelope, payload()) == first
    assert counts == {Envelope: 2, Record: 2}, "schema facts must not outlive invocation"


@pytest.mark.parametrize("mutation", ["bool", "unknown", "missing", "nested", "optional"])
def test_every_payload_is_admitted_even_after_valid_predecessors(mutation):
    value = payload()
    ir._decode(Envelope, value)
    if mutation == "bool":
        value["records"][-1]["number"] = True
    elif mutation == "unknown":
        value["records"][-1]["extra"] = 1
    elif mutation == "missing":
        del value["records"][-1]["label"]
    elif mutation == "nested":
        value["records"][-1] = {"number": 1, "label": 1}
    else:
        value["optional"] = {"number": False, "label": "wrong"}
    with pytest.raises(ValueError):
        ir._decode(Envelope, value)


def test_equal_payload_cannot_carry_admission_for_another_type():
    value = {"number": 1, "label": "ok"}
    assert ir._decode(Record, value) == Record(1, "ok")
    with pytest.raises(ValueError):
        ir._decode(Envelope, value)


def test_later_record_is_checked_within_same_traversal():
    value = payload()
    value["records"][-1]["number"] = True
    with pytest.raises(ValueError):
        ir._decode(Envelope, value)
