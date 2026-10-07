"""
Tests for scripts/context_benchmark.py — how much of a prototype the MCP tools
let an agent recover, and at what context cost.

Ground truth is read straight from the pages' markup, never through the
capture being measured.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3] / "scripts"))
from context_benchmark import (  # noqa: E402
    SearchVerdict,
    benchmark,
    classify_search,
    coverage,
    cut_notices,
    event_handlers,
    recovery_calls,
    state_names,
    style_declarations,
    visible_texts,
)
from tests.support.dc_canvas import Page, canvas_html  # noqa: E402


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


class TestCoverage:
    def test_share_of_truth_that_is_recoverable(self):
        assert coverage({"a", "b", "c", "d"}, {"a", "b", "z"}) == 0.5

    def test_empty_truth_is_not_measurable(self):
        assert coverage(set(), {"a"}) is None


class TestCutNotices:
    def test_counts_each_kind_of_cut(self):
        response = (
            "> ... +3 mais\n> ... +2 mais\n"
            '> ... +120 caracteres (chame get_full(name="Card", aspect="source") para o fonte completo)\n'
        )
        assert cut_notices(response) == {"list": 2, "source": 1}

    def test_clean_response_has_no_cuts(self):
        assert cut_notices("# Tela\nnada cortado") == {"list": 0, "source": 0}


class TestRecoveryCalls:
    def test_follows_every_recovery_hint_once(self):
        response = (
            'chame get_full(name="Card", aspect="source") … chame get_full(name="Card", aspect="source") …\n'
            '> ... +4 mais — chame `get_full(name="Card", aspect="styles")` para a lista completa\n'
            'chame get_full(screen="Home", section="Header", aspect="texts")'
        )
        assert recovery_calls(response) == [
            {"name": "Card", "aspect": "source"},
            {"name": "Card", "aspect": "styles"},
            {"screen": "Home", "section": "Header", "aspect": "texts"},
        ]


class TestClassifySearch:
    @pytest.mark.parametrize("response,verdict", [
        ("Nenhum resultado para 'logout'.", SearchVerdict.NOTHING),
        ("# Resultados para: 'x'\n> Nenhum resultado cobre todas as palavras da busca — parciais", SearchVerdict.PARTIAL),
        ("# Resultados para: 'x'\n## Component\n- **X**", SearchVerdict.FOUND),
    ])
    def test_reads_the_search_outcome(self, response, verdict):
        assert classify_search(response) == verdict


class TestBenchmark:
    @pytest.fixture(scope="class")
    def report(self, tmp_path_factory):
        tmp = tmp_path_factory.mktemp("bench")
        long_text = "Este parágrafo descreve com detalhes o que a pessoa vai encontrar ao longo do questionário."
        pages = [
            Page(f"{n} · Tela {n}", f'<div style="padding: 8px"><h1>Tela {n}</h1><p>{long_text}</p>'
                                    f'<a href="A0{n % 2 + 1}-X.dc.html" style="color: red">Seguir</a></div>')
            for n in (1, 2)
        ]
        html = tmp / "canvas.html"
        html.write_text(canvas_html(pages))
        return benchmark(html, workdir=tmp, queries=["Seguir", "logout"])

    def test_reports_the_capture_and_build(self, report):
        assert report["capture"] == "dc_canvas"
        assert report["build"]["seconds"] > 0
        assert report["build"]["write_errors"] == 0

    def test_text_coverage_counts_long_copy(self, report):
        # "Tela 1", "Tela 2", "Seguir" and the long paragraph
        assert report["texts"]["truth"] == 4
        assert report["texts"]["coverage"] == 1.0

    def test_every_page_source_comes_back_verbatim(self, report):
        assert report["round_trip"]["checked"] == 2 and report["round_trip"]["verbatim"] == 2

    def test_every_skeleton_expands_back_to_its_page(self, report):
        assert report["round_trip"]["skeletons_checked"] == 2 and report["round_trip"]["skeletons_exact"] == 2

    def test_style_coverage_is_measured_per_screen(self, report):
        assert 0 < report["styles"]["coverage"] <= 1

    def test_assembling_a_screen_is_measured_apart_from_reading_whole_sources(self, report):
        screen = report["screens"]["Tela 1"]
        assert screen["assembly_chars"] > 0 and screen["original_chars"] > len("<h1>Tela 1</h1>")
        assert screen["ratio"] == pytest.approx(screen["assembly_chars"] / screen["original_chars"])
        assert screen["source_chars"] >= 0

    def test_assembling_with_assemble_page_alone_and_in_sequence(self, report):
        first, second = (report["screens"][name] for name in ("Tela 1", "Tela 2"))
        assert first["assemble_chars"] > 0 and first["assemble_known_chars"] == first["assemble_chars"]
        assert 0 < second["assemble_known_chars"] <= second["assemble_chars"]
        assert report["assemble"]["median_ratio"] is not None and report["assemble_known"]["median_chars"] > 0

    def test_screens_are_summed_up_by_median_and_worst(self, report):
        ratios = sorted(s["ratio"] for s in report["screens"].values())
        assert report["assembly"]["median_ratio"] == pytest.approx((ratios[0] + ratios[1]) / 2)
        worst = max(report["screens"], key=lambda name: report["screens"][name]["ratio"])
        assert (report["assembly"]["worst_screen"], report["assembly"]["worst_ratio"]) == (worst, ratios[-1])
        sizes = sorted(s["assembly_chars"] for s in report["screens"].values())
        assert (report["assembly"]["median_chars"], report["assembly"]["worst_chars"]) == ((sizes[0] + sizes[1]) / 2, sizes[-1])

    def test_search_answers_are_checked_against_the_prototype(self, report):
        verdicts = {q["query"]: (q["exists"], q["verdict"]) for q in report["searches"]["queries"]}
        assert verdicts["Seguir"] == (True, "found")
        assert verdicts["logout"] == (False, "nothing")
        assert report["searches"]["correct"] == 2

    def test_formats_without_markup_ground_truth_report_not_available(self, tmp_path):
        fixtures = Path(__file__).parents[2] / "fixtures"
        result = benchmark(fixtures / "simple.html", workdir=tmp_path, queries=[])
        assert result["texts"]["coverage"] is None and result["styles"]["coverage"] is None

    def test_react_functions_come_back_verbatim(self, tmp_path):
        fixtures = Path(__file__).parents[2] / "fixtures"
        result = benchmark(fixtures / "simple.html", workdir=tmp_path, queries=[])
        assert result["round_trip"]["checked"] > 0 and result["round_trip"]["rate"] == 1.0


class TestRenderMarkdown:
    def test_summarizes_every_metric_and_lists_wrong_searches(self, tmp_path):
        from context_benchmark import render_markdown

        report = {
            "prototype": "p", "capture": "html_prototype",
            "build": {"seconds": 1.5, "phases": {}, "write_errors": 0},
            "texts": {"truth": None, "recovered": None, "coverage": None},
            "styles": {"truth": 10, "recovered": 5, "coverage": 0.5},
            "actions": {"truth": 4, "recovered": 4, "coverage": 1.0},
            "states": {"truth": 2, "recovered": 1, "coverage": 0.5},
            "assembly": {"median_ratio": 2.0, "worst_screen": "A", "worst_ratio": 3.0,
                         "median_chars": 250, "worst_chars_screen": "A", "worst_chars": 300},
            "assemble": {"median_ratio": 0.5, "worst_screen": "A", "worst_ratio": 0.8,
                         "median_chars": 50, "worst_chars_screen": "A", "worst_chars": 80},
            "assemble_known": {"median_ratio": 0.2, "worst_screen": "A", "worst_ratio": 0.3,
                               "median_chars": 20, "worst_chars_screen": "A", "worst_chars": 30},
            "screens": {"A": {"assembly_chars": 300, "source_chars": 900, "original_chars": 100, "ratio": 3.0,
                              "cuts": {"list": 2, "source": 1}, "recovery_calls": 1}},
            "searches": {"queries": [{"query": "logout", "exists": False, "verdict": "partial", "correct": False}],
                         "correct": 0, "total": 1},
        }
        markdown = render_markdown(report)
        assert "n/d (sem gabarito estático" in markdown
        assert "50% (5/10)" in markdown
        assert "| Montar uma tela com assemble_page (mediana · pior) | 50 · 80 (A) caracteres — 50% · 80% (A) do fonte da tela |" in markdown
        assert "| … telas em sequência, com known (mediana · pior) | 20 · 30 (A) caracteres — 20% · 30% (A) do fonte da tela |" in markdown
        assert "| Spec completa de uma tela (mediana · pior) | 250 · 300 (A) caracteres — 200% · 300% (A) do fonte da tela |" in markdown
        assert "| Montar todas as telas (soma) | 300 (300% do original) |" in markdown
        assert "| Ler os fontes inteiros indicados (soma) | 900 |" in markdown
        assert "listas 2 · fontes 1" in markdown
        assert "| Eventos que viram ações | 100% (4/4) |" in markdown
        assert "| Estados capturados | 50% (1/2) |" in markdown
        assert "`logout` — existe: não, resposta: partial" in markdown

    def test_a_metric_the_prototype_has_nothing_of_says_so(self):
        from context_benchmark import _coverage_cell

        assert _coverage_cell({"truth": 0, "recovered": 0, "coverage": None}) == "nenhum no protótipo"


class TestMain:
    def test_report_files_keep_dotted_prototype_names(self, tmp_path):
        from context_benchmark import main

        html = tmp_path / "Prototype v2.6.4.html"
        html.write_text(canvas_html([Page("1 · Tela", "<div><p>Olá mundo</p></div>")]))
        assert main([str(html), "--out", str(tmp_path / "out")]) == 0
        assert (tmp_path / "out" / "bench-Prototype v2.6.4.json").is_file()
        assert (tmp_path / "out" / "bench-Prototype v2.6.4.md").is_file()

    def test_missing_prototype_is_a_usage_error(self, tmp_path):
        from context_benchmark import main

        with pytest.raises(SystemExit):
            main([str(tmp_path / "absent.html")])


class TestDeclarationsShown:
    def test_style_lists_tables_and_attributes_all_count(self):
        from context_benchmark import _declarations_shown

        response = '| gap | 4px |\n- **div** `width`: `390px`\n  - `color`: `red`\n<p style="margin: 0"></p>'
        assert _declarations_shown(response) == {"gap: 4px", "width: 390px", "color: red", "margin: 0"}


    def test_without_screen_markup_one_screen_is_still_measured_in_characters(self):
        from context_benchmark import _one_screen_cell

        entry = {"median_ratio": None, "worst_screen": None, "worst_ratio": None,
                 "median_chars": 1200, "worst_chars_screen": "App", "worst_chars": 9000}
        assert _one_screen_cell(entry) == "1,200 · 9,000 (App) caracteres"


class TestOriginalIsWhatRendersTheScreen:
    def test_a_dc_screen_is_compared_with_its_whole_page_source(self, tmp_path):
        css = ".x { color: red; }" * 50
        html = tmp_path / "c.html"
        html.write_text(canvas_html([Page("1 · Tela", "<div><p>Oi</p></div>", helmet_css=css)]))
        result = benchmark(html, workdir=tmp_path, queries=[])
        assert result["screens"]["Tela"]["original_chars"] > len(css)


class TestSearchGroundTruth:
    def test_a_bundled_prototype_is_searched_in_its_unpacked_code_not_its_compressed_file(self, tmp_path):
        from context_benchmark import prototype_text
        from design_graph.capture.base import PrototypeDocument

        fixtures = Path(__file__).parents[2] / "fixtures"
        document = PrototypeDocument.read(fixtures / "large_bundle.html")
        assert "function " in prototype_text(document, "html_prototype")


class TestBehaviorGroundTruth:
    def test_each_event_attribute_with_its_whole_handler(self):
        source = '<b onClick={() => go({ a: "}" })} onMouseEnter={hover}/>'
        assert event_handlers(source) == {("click", '() => go({ a: "}" })'), ("mouseenter", "hover")}

    def test_commented_out_code_declares_nothing(self):
        source = "// <b onClick={go}/> const [a, setA] = useState(0);\n/* <i onBlur={x}/> */ const u = 'http://x'; <p onClick={ok}/>"
        assert event_handlers(source) == {("click", "ok")}
        assert state_names(source) == set()

    def test_states_declared_by_use_state_or_read_from_a_dc_state_with_a_default(self):
        assert state_names("const [open, setOpen] = React.useState(false); const [n, setN] = useState(0);") == {"open", "n"}
        assert state_names('const s = this.state || {}; const sel = s.papel ?? "eng"; x ?? 1') == {"papel"}


class TestBehaviorCoverage:
    LOGIC = """class Component extends DCLogic {
  renderVals() {
    const s = this.state || {};
    const sel = s.papel ?? "eng";
    const papel = [{"id": "dir"}, {"id": "eng"}].map((o) => ({ ...o, pick: () => this.setState({ papel: o.id }) }));
    return { papel, next: () => this.setState({ step: 2 }) };
  }
}"""
    BODY = (
        '<main><div role="group"><sc-for list="{{papel}}" as="o">'
        '<button type="button" sc-camel-on-click="{{o.pick}}"><span>{{o.id}}</span></button>'
        '</sc-for></div><button sc-camel-on-click="{{next}}">Continuar</button></main>'
    )

    def test_a_dc_page_events_and_states_are_held_as_actions_and_states(self, tmp_path):
        html = tmp_path / "c.html"
        html.write_text(canvas_html([Page("1 · Papel", self.BODY, logic=self.LOGIC)]))
        result = benchmark(html, workdir=tmp_path, queries=[])
        assert result["actions"] == {"truth": 2, "recovered": 2, "coverage": 1.0}
        assert result["states"] == {"truth": 1, "recovered": 1, "coverage": 1.0}

    def test_react_event_handlers_are_held_as_written(self, tmp_path):
        fixtures = Path(__file__).parents[2] / "fixtures"
        result = benchmark(fixtures / "simple.html", workdir=tmp_path, queries=[])
        assert result["actions"] == {"truth": 2, "recovered": 2, "coverage": 1.0}
        assert result["states"] == {"truth": 0, "recovered": 0, "coverage": None}
