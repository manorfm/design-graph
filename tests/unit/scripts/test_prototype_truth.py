"""What a prototype really says, read from its own pages — the yardstick the graph is checked against."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3] / "scripts"))
from prototype_truth import rendering_difference, style_declarations, visible_texts  # noqa: E402


def test_markup_that_renders_alike_has_no_difference():
    written = '<main>\n  <p style="color: red;margin:0">Olá   mundo</p><!-- nota --></main>'
    rebuilt = '<main><p style="margin: 0; color: red">Olá mundo</p></main>'
    assert rendering_difference(rebuilt, written) is None


def test_the_canvas_editor_hints_are_not_part_of_what_renders():
    written = '<div><sc-for list="{{xs}}" as="o" hint-placeholder-count="5"><b>{{o.label}}</b></sc-for></div>'
    rebuilt = '<div><sc-for list="{{xs}}" as="o"><b>{{o.label}}</b></sc-for></div>'
    assert rendering_difference(rebuilt, written) is None


def test_styles_and_logic_around_the_markup_are_left_to_their_own_checks():
    written = "<main><p>texto</p></main>"
    rebuilt = "<style>.tc{--ink:#111}</style><main><p>texto</p></main><script>class C {}</script>"
    assert rendering_difference(rebuilt, written) is None


def test_a_different_value_says_where_it_is():
    difference = rendering_difference('<main><p style="color: blue">a</p></main>', '<main><p style="color: red">a</p></main>')
    assert difference is not None and "main" in difference and "blue" in difference and "red" in difference


def test_missing_or_extra_elements_and_texts_are_differences():
    assert rendering_difference("<main><p>a</p></main>", "<main><p>a</p><p>b</p></main>") is not None
    assert rendering_difference("<main><p>a</p></main>", "<main><p>b</p></main>") is not None
    assert rendering_difference('<main><a href="x">a</a></main>', '<main><a href="y">a</a></main>') is not None


class TestVisibleTexts:
    def test_every_text_node_counts_whatever_its_length_or_case(self):
        markup = "<div><p>" + "a" * 200 + "</p><span>gera</span><b> 2 </b></div>"
        assert visible_texts(markup) == {"a" * 200, "gera", "2"}

    def test_interpolations_scripts_and_styles_are_not_copy(self):
        markup = "<div>{{o.label}}<script>var x = 1</script><style>p{}</style><p>Olá  mundo</p></div>"
        assert visible_texts(markup) == {"Olá mundo"}


class TestStyleDeclarations:
    def test_literal_declarations_are_normalized(self):
        markup = '<div style="color:var(--ink) ; Padding: 8px  16px"><p style="gap: 4px"></p></div>'
        assert style_declarations(markup) == {"color: var(--ink)", "padding: 8px 16px", "gap: 4px"}

    def test_interpolated_and_malformed_declarations_are_left_out(self):
        assert style_declarations('<p style="color: {{o.c}}; broken; : 1px; margin: 0"></p>') == {"margin: 0"}
