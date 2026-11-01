"""Parser-free wire contracts, below both capture adapters and the design model.

Source labels are transport vocabulary, not design entities or parser selection.
A capture interprets them; a reader must still reject unsupported stored labels
without importing a capture, discovering an engine or trusting a producer flag.
Changing a closed inventory requires a new reviewed wire-profile contract.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceKindContract:
    version: str
    source_types: tuple[str, ...]
    syntaxes: tuple[str, ...]

    def check_kind(self, source_type, syntax):
        """Admit the closed wire inventory on producer and persisted-read paths."""
        if source_type not in self.source_types or syntax not in self.syntaxes:
            raise ValueError("unsupported source kind")


BINDING_CAPTURE_V3 = SourceKindContract(
    "binding-capture/3", ("script", "module"), ("js", "jsx")
)
