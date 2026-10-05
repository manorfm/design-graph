"""
What a prototype loads besides its own code — libraries, the design tool's
runtime, its own code modules, fonts, images — identified from the embedded
files themselves (license headers, signatures, @font-face rules) and the
page's own hints. Shared by every capture that reads a bundle.

Nothing here fetches or runs anything: URLs, versions and hashes are data
read from the prototype and handed on as data.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from design_graph.model.entities import Certainty, Resource, ResourceKind

EMBEDDED = "embutido no protótipo"
_HEAD_CHARS = 2_000  # signatures and headings sit at the top of a file


@dataclass(frozen=True)
class _Signature:
    kind: ResourceKind
    name: str
    marker: re.Pattern
    version: re.Pattern | None = None


_RE_REACT_VERSION = re.compile(r"ReactVersion\s*=\s*'([\d.]+)'")
_SIGNATURES = (
    _Signature(ResourceKind.LIBRARY, "react-dom", re.compile(r"@license React\s*\*\s*react-dom\."), _RE_REACT_VERSION),
    _Signature(ResourceKind.LIBRARY, "react", re.compile(r"@license React\s*\*\s*react\."), _RE_REACT_VERSION),
    _Signature(ResourceKind.LIBRARY, "qrcode-generator", re.compile(r"QR Code Generator for JavaScript")),
    _Signature(ResourceKind.RUNTIME, "dc-runtime", re.compile(r"GENERATED from dc-runtime/")),
)
_RE_BABEL_GLOBAL = re.compile(r"\.Babel\s*=\s*\{\}")
_RE_BABEL_VERSION = re.compile(r'\.transformScriptTags=\w+,\w+\.version="([\d.]+)"')
_RE_FILE_NAME = re.compile(r"\b([\w-]+\.(?:jsx?|tsx?|mjs))\b(?:\s+(v[\d.]+))?")
_RE_DECORATION = re.compile(r"^[\s/*=─━═-]*|[\s/*=─━═-]*$")
_MAX_HEADING_CHARS = 80


def script_resource(entry_id: str, content: bytes, url: str = "") -> Resource:
    """A script the prototype embeds: a known library or runtime, else a module of its own code."""
    text = content.decode("utf-8", errors="replace")
    head = text[:_HEAD_CHARS]
    origin, certainty = (url, Certainty.STATED) if url else (EMBEDDED, Certainty.STATED)
    files = {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    for signature in _SIGNATURES:
        if signature.marker.search(head):
            version = signature.version.search(text) if signature.version else None
            return Resource.create(signature.kind, signature.name, version.group(1) if version else "",
                                   origin=origin, certainty=certainty, **files)
    if _RE_BABEL_GLOBAL.search(head):
        return Resource.create(ResourceKind.RUNTIME, "@babel/standalone", _babel_version(text),
                               origin=origin, certainty=certainty, **files)
    name, version = _module_name(head, entry_id)
    return Resource.create(ResourceKind.MODULE, name, version, origin=origin, certainty=Certainty.INFERRED, **files)


def is_infrastructure(resource: Resource) -> bool:
    """Libraries and the tool's runtime: code the prototype runs on, never code it is made of."""
    return resource.kind in (ResourceKind.LIBRARY, ResourceKind.RUNTIME)


def _babel_version(text: str) -> str:
    """Babel standalone's own version, exported right after `transformScriptTags` (the other versions are its dependencies')."""
    exported = _RE_BABEL_VERSION.search(text)
    return exported.group(1) if exported else ""


def _module_name(head: str, entry_id: str) -> tuple[str, str]:
    """
    A module's name from its opening comment: the file name it states
    (`views.jsx v2.6`), else its first line of text; a module that opens
    with code is named by its id.
    """
    lines = [line for line in (_RE_DECORATION.sub("", raw) for raw in _opening_comment(head)) if line]
    for line in lines:
        if named := _RE_FILE_NAME.search(line):
            return named.group(1), named.group(2) or ""
    if lines:
        return lines[0][:_MAX_HEADING_CHARS], ""
    return f"módulo {entry_id[:8]}", ""


def _opening_comment(head: str) -> list[str]:
    """The comment lines a file opens with, up to its first line of code."""
    lines, in_block = [], False
    for raw in head.splitlines():
        line = raw.strip()
        if not line:
            continue
        if in_block or line.startswith(("/*", "//")):
            lines.append(line)
            in_block = (in_block or line.startswith("/*")) and "*/" not in line
            continue
        break
    return lines


# ── Fonts ─────────────────────────────────────────────────────────────────────

_RE_FONT_FACE = re.compile(r"(?:/\*\s*([\w-]+)\s*\*/\s*)?@font-face\s*\{([^}]*)\}")
_RE_DESCRIPTOR = re.compile(r"([\w-]+)\s*:\s*([^;]+);?")
_RE_URL = re.compile(r"""url\(\s*["']?([^"')]+)["']?\s*\)""")
_GOOGLE_FONTS_HINTS = ("fonts.googleapis.com", "fonts.gstatic.com")


def font_resources(css: str, files: dict[str, bytes], hints: str = "") -> list[Resource]:
    """
    One resource per font family the CSS declares: its weights, styles and
    subsets (the `/* latin-ext */` comments Google Fonts writes), the bytes
    the prototype embeds for it, and where it most likely comes from.
    """
    families: dict[str, dict[str, set | int]] = {}
    for subset, body in _RE_FONT_FACE.findall(css):
        descriptors = {k.lower(): v.strip() for k, v in _RE_DESCRIPTOR.findall(body)}
        family = descriptors.get("font-family", "").strip("'\" ")
        if not family:
            continue
        found = families.setdefault(family, {"weights": set(), "styles": set(), "subsets": set(), "size": 0})
        found["weights"].add(descriptors.get("font-weight", "400"))
        found["styles"].add(descriptors.get("font-style", "normal"))
        if subset:
            found["subsets"].add(subset)
        found["size"] += sum(len(files.get(src, b"")) for src in _RE_URL.findall(descriptors.get("src", "")))
    google = any(hint in hints for hint in _GOOGLE_FONTS_HINTS)
    origin, certainty = ("Google Fonts", Certainty.INFERRED) if google else (EMBEDDED, Certainty.STATED)
    return [
        Resource.create(ResourceKind.FONT, family, origin=origin, certainty=certainty,
                        detail=_font_detail(found), size=found["size"])
        for family, found in families.items()
    ]


def _font_detail(found: dict) -> str:
    parts = [f"pesos {', '.join(sorted(found['weights']))}", ", ".join(sorted(found["styles"]))]
    if found["subsets"]:
        parts.append(f"subconjuntos {', '.join(sorted(found['subsets']))}")
    return " · ".join(parts)


# ── Images ────────────────────────────────────────────────────────────────────

def image_resource(entry_id: str, content: bytes, mime: str, role: str = "") -> Resource:
    """An image the prototype embeds, named by the role the page gives it (favicon…), else by its id."""
    return Resource.create(ResourceKind.IMAGE, role or f"imagem {entry_id[:8]}", origin=EMBEDDED,
                           certainty=Certainty.STATED, detail=mime, size=len(content),
                           sha256=hashlib.sha256(content).hexdigest())
