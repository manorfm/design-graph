"""
Which capture reads a given prototype.

Captures are consulted in order and the first one that recognizes the document
wins, so a capture for a more specific format must come before a more general
one. Adding a format means adding its capture here — nothing else in the
pipeline changes.
"""

from __future__ import annotations

from design_graph.capture.base import BindingCaptureSession, Capture, PrototypeDocument, UnsupportedPrototypeError
from design_graph.capture.dc_canvas.dc_capture import DcCanvasCapture
from design_graph.capture.html_prototype.html_capture import HtmlPrototypeCapture

CAPTURES: tuple[Capture, ...] = (
    DcCanvasCapture(),
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


def binding_capture_for(document: PrototypeDocument, *, node, toolchain, fingerprint) -> BindingCaptureSession:
    """Select the format adapter for explicit whole-unit ownership capture."""
    from design_graph.capture.binding_session import HtmlBindingSession

    # The existing source-binding profile enumerates HTML script units, including
    # bundled templates; other format families require their own adapter.
    if not HtmlPrototypeCapture().recognizes(document):
        raise UnsupportedPrototypeError("no whole-unit binding capture recognizes " + document.path.name)
    return HtmlBindingSession(document, node=node, toolchain=toolchain, fingerprint=fingerprint)


def capture_named(name: str) -> Capture:
    """The capture registered under `name` — the one a graph records it was built with."""
    for capture in CAPTURES:
        if capture.name == name:
            return capture
    raise UnsupportedPrototypeError(f"no capture named {name!r} is available")
