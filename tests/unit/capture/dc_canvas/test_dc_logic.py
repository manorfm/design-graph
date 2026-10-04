"""Literal lists a DC logic class declares, read without running it."""

from design_graph.capture.dc_canvas.logic import literal_lists


def test_json_list_is_read_with_nested_values():
    logic = 'const tabs = [{"id": "a", "items": [1, 2]}, {"id": "b", "items": []}];'
    assert literal_lists(logic) == {"tabs": [{"id": "a", "items": [1, 2]}, {"id": "b", "items": []}]}


def test_brackets_inside_strings_do_not_end_the_list():
    assert literal_lists('const xs = ["a]b", "c[d"].map(f);') == {"xs": ["a]b", "c[d"]}


def test_list_that_is_not_json_is_skipped():
    assert literal_lists("const xs = [a, b];\nconst ys = ['single'];") == {}


def test_unterminated_list_is_skipped():
    assert literal_lists('const xs = [1, 2') == {}


def test_first_declaration_of_a_name_wins():
    assert literal_lists('let xs = [1];\nlet xs = [2];') == {"xs": [1]}
