"""
Which capture reads a given prototype.

Captures are consulted in order and the first one that recognizes the document
wins, so a capture for a more specific format must come before a more general
one. Adding a format means adding its capture here — nothing else in the
pipeline changes.
"""

from __future__ import annotations

from design_graph.capture.base import Capture, PrototypeDocument, UnsupportedPrototypeError
from design_graph.capture.html_prototype import HtmlPrototypeCapture

CAPTURES: tuple[Capture, ...] = (
    HtmlPrototypeCapture(),
)


def capture_for(document: PrototypeDocument) -> Capture:
    """Return the first capture that recognizes the document."""
    for capture in CAPTURES:
        if capture.recognizes(document):
            return capture
    supported = ", ".join(capture.name for capture in CAPTURES)
    raise UnsupportedPrototypeError(
        f"{document.path.name} is not a prototype any capture recognizes (supported: {supported})"
    )
