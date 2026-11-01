"""Format-owned whole-unit inventory, custody and general capture translation."""
from hashlib import sha256
import json
from pathlib import Path

from design_graph.capture import binding_capture, binding_units


class HtmlBindingSession:
    """One invocation; no storage access or public checked-object credentials."""

    def __init__(self, document, *, node, toolchain, fingerprint):
        self.document = document
        self.producer = binding_capture.BindingCapture(
            node=node, toolchain=toolchain, fingerprint=fingerprint
        )
        self.units, self.coverage = binding_units.enumerate_units(document)
        assets = self.producer.assets
        self.adaptor = {
            p.name: sha256(p.read_bytes()).hexdigest()
            for p in sorted(assets.glob("*.mjs"))
        }
        for module in (binding_capture, binding_units):
            path = Path(module.__file__)
            self.adaptor[path.name] = sha256(path.read_bytes()).hexdigest()
        pin_path = assets / "source-syntax-pin.json"
        syntax_pin = json.loads(pin_path.read_text())
        self.syntax_fingerprint = sha256(
            json.dumps(syntax_pin, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.adaptor[pin_path.name] = sha256(pin_path.read_bytes()).hexdigest()

    def capture_source_syntax(self, source, **kwargs):
        # Preserve the producer's native method boundary and event sink.
        return self.producer.capture_source_syntax(source, **kwargs)

    async def capture_general(self, syntax_captures, owner_events, **kwargs):
        from design_graph.capture.html_prototype.parsing.source_loader import decompose
        from design_graph.capture.html_prototype.html_capture import HtmlPrototypeCapture
        from design_graph.capture.owned_emission import native_boundaries
        from design_graph.capture.owned_html_capture import OwnedHtmlPrototypeCapture

        flattened = decompose(self.document).js
        if "\n".join(u.source.decode().strip() for u in self.units) != flattened:
            # No exact translation for transformed inputs: retain normal fields
            # without promoting their unsupported provenance to owned slices.
            return await HtmlPrototypeCapture().capture(self.document, **kwargs)
        boundaries = native_boundaries(
            self.units, syntax_captures, owner_events, flattened
        )
        return await OwnedHtmlPrototypeCapture(boundaries).capture(self.document, **kwargs)
