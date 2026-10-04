"""
One DC page: the template inside <x-dc> (its <helmet> styles and markup), the
logic class in <script data-dc-script> and the editable props it declares.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from design_graph.capture.bundler import read_bundle

_RE_X_DC = re.compile(r"<x-dc(?:\s[^>]*)?>(.*)</x-dc>", re.DOTALL)
_RE_HELMET = re.compile(r"<helmet>(.*?)</helmet>", re.DOTALL)
_RE_FONT_FACE = re.compile(r"@font-face\s*\{[^}]*\}")


@dataclass(frozen=True)
class DcPage:
    markup: str        # the page's markup, helmet removed — DC directives and {{…}} kept
    styles: str        # the helmet's CSS, @font-face rules removed
    font_faces: str    # the helmet's @font-face rules
    logic: str         # body of the logic script (class Component extends DCLogic …)
    props: dict = field(default_factory=dict)  # editable props, "$"-prefixed meta keys removed

    @property
    def source(self) -> str:
        """Everything that renders the page, as the author wrote it."""
        parts = [f"<style>\n{self.styles}\n</style>"] if self.styles else []
        parts.append(self.markup)
        if self.logic:
            parts.append(f'<script type="text/x-dc">\n{self.logic}\n</script>')
        return "\n".join(parts)

    def default(self, prop: str) -> object:
        meta = self.props.get(prop)
        return meta.get("default") if isinstance(meta, dict) else None


def read_page(page_text: str) -> DcPage | None:
    """The DC page an inner bundle holds, or None when it holds something else."""
    bundle = read_bundle(page_text)
    document = bundle.template if bundle else page_text
    x_dc = _RE_X_DC.search(document)
    if not x_dc:
        return None
    inside = x_dc.group(1)
    helmet = _RE_HELMET.search(inside)
    helmet_css = "\n".join(
        style.get_text() for style in BeautifulSoup(helmet.group(1), "html.parser").find_all("style")
    ) if helmet else ""
    script = BeautifulSoup(document[x_dc.end():], "html.parser").find("script", attrs={"data-dc-script": True})
    return DcPage(
        markup=(inside[:helmet.start()] + inside[helmet.end():]).strip() if helmet else inside.strip(),
        styles=_RE_FONT_FACE.sub("", helmet_css).strip(),
        font_faces="\n".join(_RE_FONT_FACE.findall(helmet_css)),
        logic=script.get_text().strip() if script else "",
        props=_props(script.get("data-props") if script else None),
    )


def _props(raw: str | None) -> dict:
    try:
        props = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return {k: v for k, v in props.items() if not k.startswith("$")} if isinstance(props, dict) else {}
