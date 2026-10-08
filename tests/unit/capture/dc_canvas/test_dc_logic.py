"""Literal lists a DC logic class declares, read without running it."""

from design_graph.capture.dc_canvas.logic import literal_lists


def test_json_list_is_read_with_nested_values():
    logic = 'const tabs = [{"id": "a", "items": [1, 2]}, {"id": "b", "items": []}];'
    assert literal_lists(logic) == {"tabs": [{"id": "a", "items": [1, 2]}, {"id": "b", "items": []}]}


def test_brackets_inside_strings_do_not_end_the_list():
    assert literal_lists('const xs = ["a]b", "c[d"].map(f);') == {"xs": ["a]b", "c[d"]}


def test_a_list_written_in_javascript_syntax_is_read():
    assert literal_lists("const ys = [{ id: 'a', label: 'Um' }, 'b'];") == {"ys": [{"id": "a", "label": "Um"}, "b"]}


def test_a_list_holding_something_other_than_data_is_skipped():
    assert literal_lists("const xs = [a, b];\nconst ys = [f(1)];") == {}


def test_unterminated_list_is_skipped():
    assert literal_lists('const xs = [1, 2') == {}


def test_first_declaration_of_a_name_wins():
    assert literal_lists('let xs = [1];\nlet xs = [2];') == {"xs": [1]}


FACTORY_LOGIC = """
    const tab = s.tab ?? 'cap';
    const mk = (id, label) => ({ id, label, sel: String(tab === id), bg: tab === id ? 'var(--surface)' : 'transparent',
      pick: () => this.setState({ tab: id }) });
    const tabs = [mk('cap', 'Por capacidade'), mk('est', 'Por estrutura'), mk('per', 'Por perspectiva')];
"""


def test_a_list_built_by_a_local_factory_keeps_the_data_each_call_gives():
    assert literal_lists(FACTORY_LOGIC)["tabs"] == [
        {"id": "cap", "label": "Por capacidade"},
        {"id": "est", "label": "Por estrutura"},
        {"id": "per", "label": "Por perspectiva"},
    ]


def test_a_single_parameter_factory_without_parentheses_is_read():
    logic = "const item = label => ({ label });\nconst xs = [item('a'), item('b')];"
    assert literal_lists(logic) == {"xs": [{"label": "a"}, {"label": "b"}]}


def test_a_call_to_a_factory_with_arguments_it_does_not_declare_is_skipped():
    logic = "const mk = (id) => ({ id });\nconst xs = [mk('a', 'extra')];\nconst ys = [mk(other)];"
    assert literal_lists(logic) == {}


def test_a_factory_that_is_not_a_plain_object_is_skipped():
    logic = "const mk = (id) => { return { id }; };\nconst xs = [mk('a')];"
    assert literal_lists(logic) == {}


LOGIC_WITH_SLICES = """
    const ev = [{"id": "a"}, {"id": "b"}, {"id": "c"}].map((o) => ({ ...o, pick: () => go(o.id) }));
    const ev1 = ev.slice(0, 2); const ev2 = ev.slice(2);
    const last = ev.slice(-1).map((o) => o);
    const odd = ev.filter((o) => o.id !== 'b');
"""


def test_a_list_sliced_from_another_keeps_that_part_of_its_items():
    found = literal_lists(LOGIC_WITH_SLICES)
    assert found["ev1"] == [{"id": "a"}, {"id": "b"}]
    assert found["ev2"] == [{"id": "c"}]
    assert found["last"] == [{"id": "c"}]


def test_a_list_derived_in_a_way_that_cannot_be_read_is_skipped():
    found = literal_lists(LOGIC_WITH_SLICES + "const some = ev.slice(n);")
    assert "odd" not in found and "some" not in found
