"""get_full_source pages a long source instead of returning it in one response — and never loses a line."""

import re

import pytest

from design_graph.interface.mcp.full_tools import SOURCE_PAGE_CHARS, get_full_source
from design_graph.interface.mcp.tools import ToolDispatcher

_LINE = "<p>" + "a" * 990 + "</p>"


class _Reader:
    def __init__(self, source):
        self.source = source

    def get_full_source(self, name):
        return {"source_code": self.source, "source_lang": "html", "source_simplified": False}


def _body(response: str) -> str:
    return re.search(r"```html\n(.*)\n```", response, re.S).group(1)


def test_short_source_comes_in_one_response_without_pages():
    out = get_full_source(_Reader("<div>oi</div>"), "Card")
    assert "<div>oi</div>" in out and "página" not in out


def test_long_source_is_paged_and_the_pages_join_back_to_it():
    source = "\n".join([_LINE] * 50)
    reader = _Reader(source)
    first = get_full_source(reader, "Card")
    total = int(re.search(r"página 1/(\d+)", first).group(1))
    assert total > 1 and "get_full_source('Card', page=2)" in first
    pages = [_body(get_full_source(reader, "Card", page=n)) for n in range(1, total + 1)]
    assert "\n".join(pages) == source
    assert all(len(page) <= SOURCE_PAGE_CHARS for page in pages)


def test_a_single_line_longer_than_a_page_is_split_without_loss():
    source = "x" * (SOURCE_PAGE_CHARS * 2 + 10)
    reader = _Reader(source)
    total = int(re.search(r"página 1/(\d+)", get_full_source(reader, "Card")).group(1))
    assert "".join(_body(get_full_source(reader, "Card", page=n)) for n in range(1, total + 1)) == source


@pytest.mark.parametrize("page", [0, -1, 99, "dois"])
def test_out_of_range_page_says_which_pages_exist(page):
    out = get_full_source(_Reader("\n".join([_LINE] * 50)), "Card", page=page)
    assert "Página inválida" in out and "1 a " in out


def test_dispatcher_passes_the_page():
    reader = _Reader("\n".join([_LINE] * 50))
    out = ToolDispatcher([("doc", reader)]).dispatch("get_full_source", {"name": "Card", "page": 2}, "doc")
    assert "página 2/" in out
