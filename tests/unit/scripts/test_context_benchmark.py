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
    recovery_calls,
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
            "> ... +120 caracteres (chame get_full_source('Card') para o fonte completo)\n"
            "> ⚠ Extração truncada em: styles — esta spec pode estar incompleta."
        )
        assert cut_notices(response) == {"list": 2, "source": 1, "capture": 1}

    def test_clean_response_has_no_cuts(self):
        assert cut_notices("# Tela\nnada cortado") == {"list": 0, "source": 0, "capture": 0}


class TestRecoveryCalls:
    def test_follows_every_recovery_hint_once(self):
        response = (
            "chame get_full_source('Card') … chame get_full_source('Card') …\n"
            "> ... +4 mais — chame `get_full_styles(Card)` para a lista completa\n"
            "chame get_full_texts(screen=\"Home\", section=\"Header\")"
        )
        assert recovery_calls(response) == [
            ("get_full_source", {"name": "Card"}),
            ("get_full_styles", {"name": "Card"}),
            ("get_full_texts", {"screen": "Home", "section": "Header"}),
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

    def test_style_coverage_is_measured_per_screen(self, report):
        assert 0 < report["styles"]["coverage"] <= 1

    def test_assembly_cost_compares_responses_with_the_original(self, report):
        screen = report["screens"]["Tela 1"]
        assert screen["response_chars"] > 0 and screen["original_chars"] > 0
        assert screen["ratio"] == pytest.approx(screen["response_chars"] / screen["original_chars"])

    def test_search_answers_are_checked_against_the_prototype(self, report):
        verdicts = {q["query"]: (q["exists"], q["verdict"]) for q in report["searches"]["queries"]}
        assert verdicts["Seguir"] == (True, "found")
        assert verdicts["logout"] == (False, "nothing")
        assert report["searches"]["correct"] == 2

    def test_formats_without_markup_ground_truth_report_not_available(self, tmp_path):
        fixtures = Path(__file__).parents[2] / "fixtures"
        result = benchmark(fixtures / "simple.html", workdir=tmp_path, queries=[])
        assert result["texts"]["coverage"] is None and result["styles"]["coverage"] is None


class TestRenderMarkdown:
    def test_summarizes_every_metric_and_lists_wrong_searches(self, tmp_path):
        from context_benchmark import render_markdown

        report = {
            "prototype": "p", "capture": "html_prototype",
            "build": {"seconds": 1.5, "phases": {}, "write_errors": 0},
            "texts": {"truth": None, "recovered": None, "coverage": None},
            "styles": {"truth": 10, "recovered": 5, "coverage": 0.5},
            "screens": {"A": {"response_chars": 300, "original_chars": 100, "ratio": 3.0,
                              "cuts": {"list": 2, "source": 1, "capture": 0}, "recovery_calls": 1}},
            "searches": {"queries": [{"query": "logout", "exists": False, "verdict": "partial", "correct": False}],
                         "correct": 0, "total": 1},
        }
        markdown = render_markdown(report)
        assert "n/d (sem gabarito estático" in markdown
        assert "50% (5/10)" in markdown
        assert "300 (300% do original)" in markdown
        assert "listas 2 · fontes 1 · captura 0" in markdown
        assert "`logout` — existe: não, resposta: partial" in markdown


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
