"""The text a reader sees in a piece of markup — shared by every capture that reads markup."""

from bs4 import BeautifulSoup

from design_graph.capture.markup import hint_texts, visible_text_nodes, visible_texts


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


class TestHintTexts:
    def test_fields_and_tooltips_are_tagged_by_what_they_are(self):
        root = _root('<div><input placeholder="Buscar por nome"><button title="Fechar painel">x</button>'
                     '<nav aria-label="Progresso"></nav></div>')
        assert hint_texts(root) == ["[placeholder] Buscar por nome", "[dica] Fechar painel", "[dica] Progresso"]

    def test_a_described_svg_with_data_marks_is_a_chart(self):
        marks = '<circle r="2"/><circle r="3"/><polygon points="0,0 1,1"/>'
        root = _root(f'<div><svg role="img" aria-label="Radar das 8 capacidades">{marks}</svg></div>')
        assert hint_texts(root) == ["[gráfico] Radar das 8 capacidades"]

    def test_icons_decorations_and_interpolations_are_not_hints(self):
        root = _root('<div><svg aria-label="Busca"><path d="M0"/></svg>'
                     '<svg aria-hidden="true"><line/><line/><line/></svg>'
                     '<input placeholder="{{ s.hint }}"><span title="ok">a</span></div>')
        assert hint_texts(root) == ["[dica] Busca"]

    def test_each_hint_once(self):
        root = _root('<div><nav aria-label="Progresso"></nav><nav aria-label="Progresso"></nav></div>')
        assert hint_texts(root) == ["[dica] Progresso"]

    def test_the_root_own_hint_counts(self):
        nav = _root('<nav aria-label="Caminho"><a>Início</a></nav>').nav
        assert hint_texts(nav) == ["[dica] Caminho"]
