"""Tests for component_extractor single-pass — T06."""

import asyncio
from collections import Counter

import pytest

from design_graph.core.models import DesignToken
from design_graph.extraction.component_extractor import extract_all_components, extract_component
from design_graph.parsing.js_parser import find_all_boundaries
from design_graph.parsing.token_extractor import build_token_map

BTN_JS = """
function BtnPrimary() {
    return (
        <button
            className="btn-primary action-btn"
            style={{backgroundColor: '#ffb81c', padding: '8px', transition: 'all 0.2s ease'}}
            onMouseEnter={e => e.target.style.backgroundColor = '#f59e0b'}
            onMouseLeave={e => e.target.style.backgroundColor = '#ffb81c'}
        >
            Confirmar
        </button>
    )
}
"""

CARD_WITH_CHILDREN_JS = """
function RestCard() {
    return (
        <div className="rest-card">
            <Badge status="open" />
            <StarRating value={4} />
            <h3>Nome do Restaurante</h3>
            <button className="btn-primary">Pedir</button>
        </div>
    )
}
"""


def _boundary(js: str, name: str):
    bounds = find_all_boundaries(js)
    return next(b for b in bounds if b.name == name)


class TestExtractComponent:
    def test_name_matches_boundary_name(self):
        b = _boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, {})
        assert comp.name == "BtnPrimary"

    def test_comp_type_inferred_as_button(self):
        b = _boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, {})
        assert comp.comp_type == "button"

    def test_jsx_snippet_captured(self):
        b = _boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, {})
        assert "button" in comp.jsx_snippet.lower()
        assert "Confirmar" in comp.jsx_snippet

    def test_default_style_found(self):
        b = _boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, {})
        default_props = {s.property for s in comp.styles if s.state == "default"}
        assert "backgroundColor" in default_props

    def test_hover_interaction_captured(self):
        b = _boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, {})
        assert any(i.trigger == "hover" for i in comp.interactions)

    def test_hover_has_from_and_to_values(self):
        b = _boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, {})
        hover = next(i for i in comp.interactions if i.trigger == "hover")
        assert hover.to_val != ""
        assert hover.from_val != ""

    def test_button_text_extracted(self):
        b = _boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, {})
        assert any("Confirmar" in t.content for t in comp.texts)

    def test_class_names_captured(self):
        b = _boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, {})
        assert "btn-primary" in comp.classes or "action-btn" in comp.classes

    def test_child_refs_captured(self):
        b = _boundary(CARD_WITH_CHILDREN_JS, "RestCard")
        comp = extract_component(CARD_WITH_CHILDREN_JS, b, 1, {})
        assert "Badge" in comp.child_refs
        assert "StarRating" in comp.child_refs

    def test_self_not_in_child_refs(self):
        b = _boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, {})
        assert "BtnPrimary" not in comp.child_refs

    def test_react_internals_not_in_child_refs(self):
        js = "function Comp() { return (<React.Fragment><div/></React.Fragment>) }"
        b = _boundary(js, "Comp")
        comp = extract_component(js, b, 1, {})
        assert "Fragment" not in comp.child_refs
        assert "React" not in comp.child_refs

    def test_occurrence_stored_correctly(self):
        b = _boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 42, {})
        assert comp.occurrence == 42

    def test_token_map_accepted_without_error(self):
        token = DesignToken(id="c1", category="color",
                            label="primary", value="#ffb81c", usage=5)
        b = _boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, build_token_map([token]))
        assert comp is not None

    def test_styles_capped_at_limit(self):
        many = " ".join(f"style={{{{p{i}: 'v{i}'}}}}" for i in range(60))
        js = f"function ManyStyles() {{ return (<div>{many}</div>) }}"
        b = _boundary(js, "ManyStyles")
        comp = extract_component(js, b, 1, {})
        assert len(comp.styles) <= 40

    def test_texts_capped_at_limit(self):
        texts = " ".join(f'"Texto {i} é longo"' for i in range(40))
        js = f"function TextHeavy() {{ return (<div>{texts}</div>) }}"
        b = _boundary(js, "TextHeavy")
        comp = extract_component(js, b, 1, {})
        assert len(comp.texts) <= 30

    def test_child_refs_contain_no_empty_strings(self):
        b = _boundary(CARD_WITH_CHILDREN_JS, "RestCard")
        comp = extract_component(CARD_WITH_CHILDREN_JS, b, 1, {})
        assert all(ref for ref in comp.child_refs)


class TestExtractAllComponents:
    def test_extracts_multiple_components(self):
        js = BTN_JS + CARD_WITH_CHILDREN_JS
        bounds = find_all_boundaries(js)
        occ = Counter(b.name for b in bounds)
        comps = asyncio.run(extract_all_components(js, bounds, occ, {}))
        names = {c.name for c in comps}
        assert "BtnPrimary" in names
        assert "RestCard" in names

    def test_no_duplicates_in_concurrent_run(self):
        funcs = "\n".join(
            f"function Component{i:02d}() {{ return (<div>comp{i}</div>) }}"
            for i in range(20)
        )
        bounds = find_all_boundaries(funcs)
        occ = Counter(b.name for b in bounds)
        comps = asyncio.run(extract_all_components(funcs, bounds, occ, {}))
        names = [c.name for c in comps]
        assert len(names) == len(set(names))

    def test_works_with_concurrency_one(self):
        bounds = find_all_boundaries(BTN_JS)
        occ = Counter(b.name for b in bounds)
        comps = asyncio.run(extract_all_components(BTN_JS, bounds, occ, {}, concurrency=1))
        assert len(comps) >= 1

    def test_empty_boundaries_returns_empty(self):
        comps = asyncio.run(extract_all_components("", [], Counter(), {}))
        assert comps == []
