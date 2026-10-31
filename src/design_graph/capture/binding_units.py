"""Whole original script units, never the legacy concatenation or component slices.

Script order is provenance only; units deliberately do not assert runtime linkage.
Unfetched external scripts, infrastructure, non-code and unsupported options are
explicit coverage omissions. No engine is installed or discovered here.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from bs4 import BeautifulSoup

from design_graph.capture.bundler import read_bundle
from design_graph.capture.resources import is_infrastructure, script_resource


@dataclass(frozen=True)
class ScriptUnit:
    locator: str
    source: bytes
    source_type: str
    syntax: str

    def metadata(self):
        return {
            "locator": self.locator,
            "source_sha256": sha256(self.source).hexdigest(),
            "byte_length": len(self.source),
            "source_type": self.source_type,
            "syntax": self.syntax,
        }


def enumerate_units(document):
    """Return deterministic complete input inventory and explicit exclusions."""
    bundle = read_bundle(document.text)
    units, coverage, referenced = [], [], set()
    html = bundle.template if bundle else document.text
    prefix = "template" if bundle else "document"
    for order, tag in enumerate(BeautifulSoup(html, "html.parser").find_all("script")):
        locator = f"{document.path.resolve()}#{prefix}/script/{order}"
        mime = str(tag.get("type", "")).lower().strip()
        source_type = "module" if mime == "module" else "script"
        syntax = "jsx" if mime in ("text/babel", "text/jsx") else "js"
        src = tag.get("src")
        reason = None
        if mime not in (
            "",
            "module",
            "text/javascript",
            "application/javascript",
            "text/babel",
            "text/jsx",
        ):
            reason = "unsupported-script-type"
        if any(
            tag.has_attr(key)
            for key in ("data-presets", "data-plugins", "data-type", "language")
        ):
            reason = "unsupported-script-options"
        content = tag.get_text().encode("utf8")
        if src:
            if bundle and src in bundle.manifest:
                referenced.add(src)
                locator += "/bundle/" + src
                content = bundle.entry(
                    src
                )  # decoding errors fail capture, never disappear
                if is_infrastructure(script_resource(src, content)):
                    reason = "infrastructure"
            else:
                reason = reason or "external-script-not-fetched"
                content = b""
        record = {
            "locator": locator,
            "order": order,
            "src": src,
            "mime": mime,
            "source_type": source_type,
            "syntax": syntax,
            "async_": tag.has_attr("async"),
            "defer": tag.has_attr("defer"),
        }
        if reason:
            coverage.append({**record, "status": "excluded", "reason": reason})
        else:
            unit = ScriptUnit(locator, content, source_type, syntax)
            units.append(unit)
            coverage.append({**record, **unit.metadata(), "status": "captured"})
    if bundle:
        for key in sorted(set(bundle.manifest) - referenced):
            coverage.append(
                {
                    "locator": f"{document.path.resolve()}#bundle/{key}",
                    "status": "excluded",
                    "reason": "unreferenced-bundle-entry",
                    "mime": bundle.manifest[key].get("mime", ""),
                }
            )
        for order, tag in enumerate(
            BeautifulSoup(document.text, "html.parser").find_all("script")
        ):
            coverage.append(
                {
                    "locator": f"{document.path.resolve()}#container/script/{order}",
                    "status": "excluded",
                    "reason": "bundle-container-not-program",
                    "mime": str(tag.get("type", "")),
                }
            )
    return tuple(units), coverage
