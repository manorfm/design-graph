"""get_full_source returns a long source in parts instead of one response — and never loses a line."""

import re

import pytest

from design_graph.interface.mcp.full_tools import MID_LINE_NOTICE, SOURCE_PART_CHARS, get_full_source
from design_graph.interface.mcp.tools import ToolDispatcher

_LINE = "<p>" + "a" * 990 + "</p>"


class _Reader:
    def __init__(self, source):
        self.source = source

    def get_full_source(self, name):
        return {"source_code": self.source, "source_lang": "html"}


def _body(response: str) -> str:
    return re.search(r"```html\n(.*)\n```", response, re.S).group(1)


def test_short_source_comes_in_one_response_without_parts():
    out = get_full_source(_Reader("<div>oi</div>"), "Card")
    assert "<div>oi</div>" in out and "parte" not in out


def test_long_source_comes_in_parts_that_join_back_to_it():
    source = "\n".join([_LINE] * 50)
    reader = _Reader(source)
    first = get_full_source(reader, "Card")
    total = int(re.search(r"parte 1/(\d+)", first).group(1))
    assert total > 1 and "get_full_source('Card', part=2)" in first
    parts = [_body(get_full_source(reader, "Card", part=n)) for n in range(1, total + 1)]
    assert "\n".join(parts) == source
    assert all(len(part) <= SOURCE_PART_CHARS for part in parts)


def test_a_line_longer_than_a_part_says_where_it_continues():
    source = "<p>a</p>\n" + "x" * (SOURCE_PART_CHARS * 2 + 10) + "\n<p>b</p>"
    reader = _Reader(source)
    total = int(re.search(r"parte 1/(\d+)", get_full_source(reader, "Card")).group(1))
    joined = ""
    for n in range(1, total + 1):
        response = get_full_source(reader, "Card", part=n)
        joined += _body(response) + ("" if n == total or MID_LINE_NOTICE in response else "\n")
    assert joined == source


@pytest.mark.parametrize("part", [0, -1, 99, "dois"])
def test_out_of_range_part_says_which_parts_exist(part):
    out = get_full_source(_Reader("\n".join([_LINE] * 50)), "Card", part=part)
    assert "Parte inválida" in out and "1 a " in out


def test_dispatcher_passes_the_part():
    reader = _Reader("\n".join([_LINE] * 50))
    out = ToolDispatcher([("doc", reader)]).dispatch("get_full_source", {"name": "Card", "part": 2}, "doc")
    assert "parte 2/" in out
