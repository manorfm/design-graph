"""What an element looks like, in words a name can carry — read from its own literal styles and attributes."""

import pytest
from bs4 import BeautifulSoup

from design_graph.capture.dc_canvas.traits import shared_traits, traits_of


def _element(markup: str):
    return BeautifulSoup(markup, "html.parser").find()


@pytest.mark.parametrize("markup,expected", [
    ('<div style="font-size: 12px; font-weight: 600; text-transform: uppercase">x</div>', ["Caps", "Bold", "Small"]),
    ("<span style=\"font-family: Newsreader, Georgia, serif; font-size: 20px; font-weight: 600\">x</span>", ["Serif", "Bold"]),
    ("<h1 style=\"font-family: Newsreader, serif; font-size: clamp(30px, 4.2vw, 52px)\">x</h1>", ["Serif", "Large"]),
    ('<span style="display: inline-flex; border-radius: 999px; font-size: 12px">x</span>', ["Pill", "Small"]),
    ('<a style="background: var(--accent); color: var(--on-accent); font-weight: 600">x</a>', ["Accent", "Bold"]),
    ('<span aria-hidden="true" style="display: flex"></span>', ["Decorative"]),
    ("<p style=\"font-family: 'IBM Plex Sans', sans-serif; font-size: 16px\">x</p>", []),
])
def test_traits_come_from_the_element_own_styles(markup, expected):
    assert traits_of(_element(markup)) == expected


def test_a_soft_accent_background_is_not_an_accent():
    assert traits_of(_element('<div style="background: var(--accent-soft)">x</div>')) == []


def test_interpolated_values_say_nothing():
    assert traits_of(_element('<div style="font-weight: {{o.fw}}; text-transform: {{o.tt}}">x</div>')) == []


def test_only_traits_every_occurrence_has_are_shared_in_their_order():
    caps_bold = _element('<div style="font-weight: 600; text-transform: uppercase">a</div>')
    caps = _element('<div style="font-weight: 400; text-transform: uppercase">b</div>')
    assert shared_traits([caps_bold, caps]) == ["Caps"]
    assert shared_traits([]) == []


@pytest.mark.parametrize("markup,expected", [
    ('<div style="display: flex"><span>eyebrow</span><h1>Título</h1><p>texto</p></div>', "Heading"),
    ('<div style="display: grid"><button>a</button><button>b</button></div>', "Button"),
    ('<div style="display: flex"><fieldset><legend>q</legend></fieldset><a href="#">Voltar</a></div>', "Fieldset"),
    ('<div style="display: flex"><svg></svg><p>legenda</p></div>', "Chart"),
    ('<div style="display: flex"><sc-for list="{{xs}}" as="o"><a href="#">{{o.label}}</a></sc-for></div>', "Link"),
    ('<div style="display: flex"><span>a</span><div>b</div></div>', ""),
])
def test_a_container_is_known_by_the_most_telling_thing_it_holds(markup, expected):
    from design_graph.capture.dc_canvas.traits import main_content

    assert main_content(_element(markup)) == expected
