"""
Sources are captured whole: a screen section, a semantic HTML section and a
repeated DOM pattern keep every character of their markup, however long.
"""

from bs4 import BeautifulSoup

from design_graph.capture.html_prototype.extraction.plain_html_component_extractor import (
    dom_pattern_to_extracted_component,
)
from design_graph.capture.html_prototype.extraction.section_extractor import _build_section
from design_graph.capture.html_prototype.parsing.html_parser import extract_dom_patterns, extract_semantic_sections

_LONG = "".join(f'<p class="linha">Parágrafo número {n} com conteúdo.</p>' for n in range(200))


def test_jsx_section_source_is_whole():
    section = _build_section(block=f"<div>{_LONG}</div>", sec_name="Lista", screen_name="Home", detection_method="comment")
    assert section.source_code == f"<div>{_LONG}</div>"


def test_semantic_section_html_is_whole():
    soup = BeautifulSoup(f"<main><section>{_LONG}</section></main>", "html.parser")
    section = next(s for s in extract_semantic_sections(soup) if s["tag"] == "section")
    assert section["html"] == f"<section>{_LONG}</section>"


def test_repeated_pattern_example_is_whole():
    card = '<div class="card"><h3>T</h3>' + "".join(f"<span>{n}</span>" for n in range(150)) + "</div>"
    soup = BeautifulSoup(f"<body>{card * 3}</body>", "html.parser")
    pattern = next(p for p in extract_dom_patterns(soup) if p.first_example.startswith('<div class="card">'))
    assert pattern.first_example == card
    assert dom_pattern_to_extracted_component(pattern).source_code == card
