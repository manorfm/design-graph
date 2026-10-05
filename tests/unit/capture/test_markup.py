"""The text a reader sees in a piece of markup — shared by every capture that reads markup."""

from bs4 import BeautifulSoup

from design_graph.capture.markup import visible_text_nodes, visible_texts


def _root(markup: str):
    return BeautifulSoup(markup, "html.parser")


def test_every_text_node_is_copy_whatever_its_length_case_or_tag():
    paragraph = "Em vez de opiniões gerais, vamos pedir que você pense em casos reais e recentes. " * 3
    markup = f"<div><p>{paragraph}</p><li>gera</li><td>60%+</td><span>·</span><div>Bloco</div></div>"
    assert visible_texts(_root(markup)) == [paragraph.strip(), "gera", "60%+", "·", "Bloco"]


def test_whitespace_is_collapsed_and_repeats_kept_once():
    assert visible_texts(_root("<p>Olá   \n mundo</p><p>Olá mundo</p>")) == ["Olá mundo"]


def test_scripts_styles_comments_and_interpolations_are_not_copy():
    markup = "<div><script>var x</script><style>p{}</style><!-- note --><p>{{o.label}}</p><p>Real</p></div>"
    assert visible_texts(_root(markup)) == ["Real"]


def test_each_text_comes_with_the_element_showing_it():
    nodes = visible_text_nodes(_root("<h2>Título</h2><button>Salvar</button>"))
    assert nodes == [("Título", "h2"), ("Salvar", "button")]


def test_element_names_can_be_mapped_by_the_caller():
    nodes = visible_text_nodes(_root("<sc-raw-td>Fluxo</sc-raw-td>"), tag_of=lambda el: el.name.removeprefix("sc-raw-"))
    assert nodes == [("Fluxo", "td")]
