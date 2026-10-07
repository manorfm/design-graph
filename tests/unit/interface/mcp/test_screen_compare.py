"""get_screen(name, compare=other): only what one of two screens has and the other does not."""

from design_graph.interface.mcp import screen_tools

CONTENTS = {
    "Home": {"name": "Home", "components": ["Cell", "Grid"], "texts": ["Olá", "Só no celular"],
             "styles": ["gap: 8px", "width: 390px"]},
    "Home (desktop)": {"name": "Home (desktop)", "components": ["Cell", "Grid", "Sidebar"], "texts": ["Olá"],
                       "styles": ["gap: 8px", "width: 390px"]},
}


class _Reader:
    def screen_contents(self, name):
        return CONTENTS.get(name)


def _compare(name="Home", other="Home (desktop)"):
    return screen_tools.get_screen(_Reader(), name, compare=other)


def test_what_only_one_screen_has_is_listed_under_it():
    text = _compare()
    assert "# Home × Home (desktop)" in text
    assert "- só em **Home (desktop)**: `Sidebar`" in text
    assert "- só em **Home**: \"Só no celular\"" in text


def test_an_aspect_both_share_is_said_to_be_equal_with_its_count():
    text = _compare()
    assert "## Estilos\n- iguais nas duas (2)" in text
    assert "## Componentes\n- só em **Home (desktop)**: `Sidebar`\n- em comum: 2" in text


def test_an_unknown_screen_is_named():
    assert _compare(other="Nada") == "Tela 'Nada' não encontrada."


def test_screens_alike_in_everything_point_to_the_tokens_by_mode(monkeypatch):
    monkeypatch.setitem(CONTENTS, "Home (escuro)", {**CONTENTS["Home"], "name": "Home (escuro)"})
    assert "get_tokens(mode=…)" in _compare(other="Home (escuro)")
