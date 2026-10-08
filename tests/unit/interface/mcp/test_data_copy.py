"""The copy a component's referenced data holds, for search."""

import pytest

from design_graph.interface.mcp.data_copy import MAX_COPY_LENGTH, copy_in, reads_as_copy


def test_copy_is_found_at_any_depth_in_order_and_once():
    data = {
        "tabs": [{"id": "cap", "label": "Por capacidade", "sub": {"hint": "Domínios"}}, {"label": "Por capacidade"}],
        "rows": [["Engenharia", 22]],
    }
    assert copy_in(data) == [
        ("tabs", "cap"), ("tabs", "Por capacidade"), ("tabs", "Domínios"), ("rows", "Engenharia"),
    ]


@pytest.mark.parametrize("text", ["Engenharia", "Não sei", "faixa 18–31%", "Ir"])
def test_words_read_as_copy(text):
    assert reads_as_copy(text)


@pytest.mark.parametrize("text", [
    "", "   ", "M12 2L2 7l10 5 10-5-10-5z", "M 10 10 L 20 20", "#0D5C63", "#fff", "#abcdef", "12px", "1.5rem", "A", "a" * (MAX_COPY_LENGTH + 1),
])
def test_drawing_data_and_oversized_values_do_not(text):
    assert not reads_as_copy(text)
