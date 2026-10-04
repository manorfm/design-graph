"""
The self-unpacking HTML bundle format several prototype tools export: a
manifest of base64 (optionally gzip) files, a template page that references
them by id, and the order pages were authored in — each in a
<script type="__bundler/…"> element.

Shared by every capture that reads such bundles; it knows the container, not
what is inside it.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import zlib
from dataclasses import dataclass

# Largest file one manifest entry may expand to. Real entries stay under a
# few MB; the cap stops a crafted entry from inflating without bound.
MAX_ENTRY_BYTES = 64 * 1024 * 1024

_RE_BUNDLE_SCRIPT = re.compile(r'<script type="__bundler/(\w+)">(.*?)</script>', re.DOTALL)


class BundleEntryError(ValueError):
    """A manifest entry that cannot be decoded."""


@dataclass(frozen=True)
class Bundle:
    manifest: dict[str, dict]  # id → {"mime", "compressed", "data"}
    template: str              # the page that lays the bundle out
    page_order: list[str]

    def entry(self, entry_id: str) -> bytes:
        """The decoded content of one manifest entry; raises BundleEntryError."""
        entry = self.manifest.get(entry_id)
        if not isinstance(entry, dict) or not isinstance(entry.get("data"), str):
            raise BundleEntryError(f"bundle has no file {entry_id!r}")
        return decode_entry(entry)


def read_bundle(text: str) -> Bundle | None:
    """The bundle a document carries, or None when it isn't one."""
    scripts = {name: body.strip() for name, body in _RE_BUNDLE_SCRIPT.findall(text)}
    if "manifest" not in scripts or "template" not in scripts:
        return None
    try:
        manifest = json.loads(scripts["manifest"])
        template = json.loads(scripts["template"])
        page_order = json.loads(scripts.get("page_order") or "[]")
    except json.JSONDecodeError:
        return None
    if not isinstance(manifest, dict) or not isinstance(template, str) or not isinstance(page_order, list):
        return None
    return Bundle(manifest=manifest, template=template, page_order=[str(i) for i in page_order])


def decode_entry(entry: dict) -> bytes:
    """Strict base64, then gzip when flagged — bounded by MAX_ENTRY_BYTES."""
    try:
        raw = base64.b64decode(entry["data"], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise BundleEntryError(f"invalid base64: {exc}") from exc
    if not entry.get("compressed"):
        return raw
    inflater = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
    try:
        content = inflater.decompress(raw, MAX_ENTRY_BYTES)
    except zlib.error as exc:
        raise BundleEntryError(f"invalid gzip: {exc}") from exc
    if inflater.unconsumed_tail:
        raise BundleEntryError(f"entry expands beyond {MAX_ENTRY_BYTES} bytes")
    return content
