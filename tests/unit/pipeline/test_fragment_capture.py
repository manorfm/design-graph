"""The pipeline reads a fragment with the capture a prototype was built with."""

import pytest

from design_graph.pipeline.coordinator import UnsupportedPrototypeError, capture_fragment


def test_fragment_is_read_by_the_named_capture():
    comp = capture_fragment("html_prototype", '<span style={{color: "blue"}}>Hi there</span>')
    assert ("color", "blue") in {(s.property, s.value) for s in comp.styles}


def test_unknown_capture_is_unsupported():
    with pytest.raises(UnsupportedPrototypeError):
        capture_fragment("no_such_capture", "<div/>")
