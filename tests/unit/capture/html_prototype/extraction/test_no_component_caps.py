"""A component keeps every style, interaction, class and prop it declares — however many."""

from design_graph.capture.html_prototype.extraction.component_extractor import extract_component
from design_graph.capture.html_prototype.extraction.plain_html_component_extractor import (
    dom_pattern_to_extracted_component,
)
from design_graph.capture.html_prototype.extraction.prop_extractor import extract_props_from_function_signature
from design_graph.capture.html_prototype.parsing.js_parser import find_all_boundaries
from design_graph.capture.html_prototype.sources import DOMPattern


def _boundary(js, name):
    return next(b for b in find_all_boundaries(js) if b.name == name)


def test_every_inline_style_is_kept():
    styles = ", ".join(f"prop{i}: 'val{i}px'" for i in range(60))
    js = f"function Heavy() {{ return <div style={{{{{styles}}}}}>x</div>; }}"
    comp = extract_component(js, _boundary(js, "Heavy"), 1)
    assert {s.property for s in comp.styles} >= {f"prop{i}" for i in range(60)}


def test_every_hover_interaction_is_kept():
    handlers = "\n".join(
        f"onMouseEnter={{e => e.target.style.prop{i} = 'val{i}'}}\n"
        f"onMouseLeave={{e => e.target.style.prop{i} = 'orig{i}'}}"
        for i in range(20)
    )
    js = f"function Hover() {{ return (<div\n{handlers}\n>x</div>); }}"
    comp = extract_component(js, _boundary(js, "Hover"), 1)
    assert len(comp.interactions) == 20


def test_every_class_is_kept():
    classes = " ".join(f"cls{i}" for i in range(15))
    js = f'function Classy() {{ return <div className="{classes}" />; }}'
    comp = extract_component(js, _boundary(js, "Classy"), 1)
    assert comp.classes.split() == [f"cls{i}" for i in range(15)]


def test_every_prop_is_kept():
    many = ", ".join(f"prop{i}" for i in range(40))
    js = f"function BigComp({{ {many} }}) {{ return <div/>; }}"
    assert len(extract_props_from_function_signature(js, _boundary(js, "BigComp"))) == 40


def test_long_plain_html_style_value_is_kept():
    value = "linear-gradient(90deg, rgba(0,0,0,.1) 0%, rgba(0,0,0,.2) 50%, rgba(0,0,0,.3) 100%)"
    pattern = DOMPattern(signature="div>p", count=3, first_example=f'<div style="background: {value}"><p>x</p></div>',
                         inferred_name="Banner", semantic_type="card")
    comp = dom_pattern_to_extracted_component(pattern)
    assert [(s.property, s.value) for s in comp.styles] == [("background", value)]


def test_the_model_has_no_truncation_record():
    from design_graph.model.entities import ExtractedComponent
    from design_graph.model.graph.schema import node_tables

    assert "truncated_fields" not in ExtractedComponent.__dataclass_fields__
    assert "truncated_fields" not in node_tables()["Component"].columns
