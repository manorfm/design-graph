"""Values a DC logic class writes literally, read without running any of it."""

import pytest

from design_graph.capture.dc_canvas.literals import NotALiteral, read_literal


def _value(text: str, names: dict | None = None):
    return read_literal(text, 0, names).value


def test_json_values_are_read():
    assert _value('[{"id": "a", "n": [1, -2.5, 3e2]}, true, false, null]') == [
        {"id": "a", "n": [1, -2.5, 300.0]}, True, False, None,
    ]


def test_javascript_object_syntax_is_read():
    assert _value("{ id: 'cap', \"label\": `Por capacidade`, 3: 'x', }") == {
        "id": "cap", "label": "Por capacidade", "3": "x",
    }


def test_escapes_inside_strings_are_decoded():
    assert _value(r"['it\'s', " + '"a\\"b", "\\u00e7\\n"]') == ["it's", 'a"b', "ç\n"]


def test_comments_are_skipped():
    assert _value("[ // first\n 'a', /* second */ 'b' ]") == ["a", "b"]


def test_the_end_is_just_past_the_value():
    text = "const xs = ['a'].map(f);"
    found = read_literal(text, text.index("["))
    assert text[found.end:] == ".map(f);"


def test_a_bound_name_reads_as_its_value_and_shorthand_members_use_it():
    assert _value("{ id, label, kind: id }", {"id": "cap", "label": "Por capacidade"}) == {
        "id": "cap", "label": "Por capacidade", "kind": "cap",
    }


def test_members_that_are_behaviour_are_left_out_of_an_object():
    text = "{ ...o, id, sel: String(tab === id), bg: tab === id ? 'a' : 'b', fw: id ? 1 : 2, pick: () => go({ x: 1 }), label }"
    assert _value(text, {"id": "cap", "label": "Corte"}) == {"id": "cap", "label": "Corte"}


@pytest.mark.parametrize("text", [
    "[a, 'b']",              # a name nothing binds
    "[`total ${n}`]",        # an interpolated template
    "['a', ...rest]",        # a spread element
    "[f('a')]",              # a call
    "['a', 'b'",             # unterminated
    "'open",                 # unterminated string
    "{ id: 'a' ",            # unterminated object
    "",                      # nothing at all
])
def test_what_is_not_a_literal_is_refused(text):
    with pytest.raises(NotALiteral):
        read_literal(text, 0)


def test_nesting_beyond_the_limit_is_refused_instead_of_exhausting_the_stack():
    with pytest.raises(NotALiteral):
        read_literal("[" * 5000 + "]" * 5000, 0)


def test_a_call_is_read_only_through_a_function_the_caller_defines():
    calls = {"pair": lambda args: {"id": args[0], "label": args[1]}}
    assert read_literal("[pair('a', 'Um'), pair('b', 'Dois')]", 0, calls=calls).value == [
        {"id": "a", "label": "Um"}, {"id": "b", "label": "Dois"},
    ]
    with pytest.raises(NotALiteral):
        read_literal("[other('a')]", 0, calls=calls)
